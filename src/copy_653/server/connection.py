"""Per-connection state and the WS dispatch loop.

One :class:`ConnectionState` lives per WS connection (one browser tab).
It owns the four per-slot task references (session / letter / test
message / key input), the optional browser-key-input state, and the
optional active Cadence session.

Stateless action coroutines live in small modules under :mod:`copy_653.server`;
this module is the only caller of them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol

from copy_653.audio import patterns, timing
from copy_653.config import (
    DEFAULT_CONFIG_PATH,
    load_audio_parameters,
    load_claimed_symbols,
    load_keyer_settings,
    load_save_directory,
    load_warm_up_timeout_seconds,
)
from copy_653.letters import ANCHORED_SYMBOLS, find_anchors_dir
from copy_653.midi import KeyDecoder, KeyElementAssembler
from copy_653.server.audio_settings_actions import (
    _get_audio_settings_action,
    _get_audio_output_devices_action,
    _play_audio_output_test_action,
    _set_audio_settings_action,
    _set_audio_output_device_action,
)
from copy_653.server.voice_settings_actions import (
    _set_voice_input_device_action,
    _get_voice_settings_action,
    _set_voice_settings_action,
)
from copy_653.server.actions import (
    _claim_symbol_action,
    _play_copy_key_exercise,
    _request_copy_exercises_action,
    _request_copy_key_exercises_action,
    _save_koch_answers_action,
    _save_recognition_answers_action,
    _start_action,
    _start_warmup_action,
    _unclaim_symbol_action,
)
from copy_653.server.key_input_actions import (
    BrowserKeyInputState,
    KeyNoteSource,
    _push_key_note_event,
    _run_key_input_action,
)
from copy_653.server.test_message_actions import (
    _play_test_message_action,
    _save_test_message_action,
)
from copy_653.server.texture_preview_actions import (
    _play_texture_preview_loop,
    _save_texture_preview_action,
)
from copy_653.server.letter_playback_actions import (
    _run_letter_sequence,
    _run_morse_repeat,
)
from copy_653.server.recognition_actions import (
    ActiveRecognitionSession,
    _coerce_recognition_diagnostic,
    _coerce_recognition_exercise_completion,
    _recognition_kind_for_gear,
    _run_recognition_receiver_bed_loop,
    _run_recognition_session,
    _start_recognition_action,
)
from copy_653.server.records import (
    _ActiveCadenceSession,
    _ActiveCopyKeySession,
    _finalize_cadence_session,
    _finalize_copy_key_session,
    _iter_koch_records,
    _iter_recognition_records,
    _koch_readiness_state,
    _next_send_symbol_readiness,
    _resolve_recognition_session_gears,
    _resolve_session_gears_and_rst,
)
from copy_653.server.validation import (
    _browser_midi_note_event,
    _optional_positive_int,
)
from copy_653.server.wire_events import (
    _claimed_symbols_event,
    _key_input_start_payload,
    _send_event,
)

logger = logging.getLogger(__name__)


async def supersede(task: asyncio.Task[Any] | None) -> None:
    """Cancel and await an in-flight per-slot task; swallow cancellation.

    The handler uses this to retire whatever was running in a task slot
    before starting its replacement, so event ordering on the new task's
    first frame is preserved. A ``None`` or already-completed task is a
    no-op.
    """
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


@dataclass
class ConnectionState:
    """All per-WS-connection state.

    Owns per-slot task references (session, letter, test-message,
    texture-preview, key-input, copy-key-play), the optional
    browser-key-input state, and the optional active Cadence session.
    The dispatch loop in :func:`handler` is the only mutator.
    """

    ws: WebSocketServerProtocol
    config_path: Path
    anchors_dir: Path
    key_note_source: KeyNoteSource | None = None
    session_task: asyncio.Task[None] | None = None
    letter_task: asyncio.Task[None] | None = None
    test_message_task: asyncio.Task[None] | None = None
    texture_preview_task: asyncio.Task[None] | None = None
    key_input_task: asyncio.Task[None] | None = None
    recognition_floor_task: asyncio.Task[None] | None = None
    browser: BrowserKeyInputState | None = None
    cadence: _ActiveCadenceSession | None = None
    copy_key: _ActiveCopyKeySession | None = None
    copy_key_play_task: asyncio.Task[None] | None = None
    # Path to the koch-exercise record written at the last session-end,
    # awaiting a `save-koch-answers` rewrite. Cleared on a new `start`,
    # on successful save, or when the connection closes.
    pending_koch_record_path: Path | None = None
    # Koch exercise set state machine. A set is 8 sessions: 2 warm-up
    # (pair recognition) followed by 6 main (full-burden). The warm-up
    # re-engages when the gap since the last session exceeds the
    # configured timeout, but the main counter resumes where it was.
    warmup_remaining: int = 2
    main_session_next: int = 3
    last_session_ended_at: float | None = None
    set_id: str = ""
    # Symbol Recognition set state machine. 8 sessions, no warm-up.
    recognition_session_next: int = 1
    recognition_set_id: str = ""
    recognition_last_session_ended_at: float | None = None
    pending_recognition_record_path: Path | None = None
    recognition: ActiveRecognitionSession | None = None

    @property
    def is_fresh_set(self) -> bool:
        return self.warmup_remaining == 2 and self.main_session_next == 3

    @property
    def is_recognition_fresh_set(self) -> bool:
        return self.recognition_session_next == 1

    def cadence_recorder(self, event: dict[str, Any]) -> None:
        """Forward an outbound key/sent event to the active Cadence record."""
        if self.cadence is not None:
            self.cadence.record_event(event)

    def copy_key_recorder(self, event: dict[str, Any]) -> None:
        """Forward an outbound key/sent event to the active Copy Key record."""
        if self.copy_key is not None:
            self.copy_key.record_event(event)

    def active_recorder(self, event: dict[str, Any]) -> None:
        """Forward a key/sent event to whichever session is active."""
        if self.copy_key is not None:
            self.copy_key.record_event(event)
        elif self.cadence is not None:
            self.cadence.record_event(event)

    def close_active_cadence_session(self) -> None:
        """Persist and clear any in-flight Cadence session."""
        if self.cadence is not None:
            _finalize_cadence_session(self.cadence, self.config_path)
            self.cadence = None

    def close_active_copy_key_session(self) -> None:
        """Persist and clear any in-flight Copy Key session."""
        if self.copy_key is not None:
            _finalize_copy_key_session(self.copy_key, self.config_path)
            self.copy_key = None


def _reconstruct_set_state(state: ConnectionState) -> None:
    """Restore the set state machine from persisted records on connect.

    A page refresh creates a fresh ConnectionState, losing the in-memory
    set position. This reads recent koch-exercise records and restores
    warmup_remaining, main_session_next, set_id, and last_session_ended_at
    so the learner resumes where they left off instead of restarting from
    warm-up 1.
    """
    try:
        save_directory = load_save_directory(state.config_path)
    except Exception:
        return

    records = _iter_koch_records(save_directory)
    if not records:
        return

    by_set: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        gen = r.get("generation") or {}
        sid = gen.get("set_id")
        if isinstance(sid, str) and sid:
            by_set.setdefault(sid, []).append(r)

    if not by_set:
        return

    latest_set_id = max(by_set)
    group = by_set[latest_set_id]

    max_session = 0
    latest_ended: datetime | None = None
    for r in group:
        gen = r.get("generation") or {}
        ss = gen.get("set_session")
        if isinstance(ss, int) and not isinstance(ss, bool) and ss > max_session:
            max_session = ss
        ended = r.get("ended_at")
        if isinstance(ended, str):
            try:
                dt = datetime.fromisoformat(ended.replace("Z", "+00:00"))
                if latest_ended is None or dt > latest_ended:
                    latest_ended = dt
            except ValueError:
                continue

    if max_session == 0 or max_session >= 8 or latest_ended is None:
        return

    elapsed = (datetime.now(timezone.utc) - latest_ended).total_seconds()
    state.set_id = latest_set_id
    state.last_session_ended_at = time.monotonic() - elapsed

    if max_session <= 2:
        state.warmup_remaining = 2 - max_session
        state.main_session_next = 3
    else:
        state.warmup_remaining = 0
        state.main_session_next = max_session + 1


async def _run_start_session(state: ConnectionState) -> None:
    """Wrap a `start` action with the set state machine, common
    invalid-config and stop-was-requested handlers.

    The state machine decides whether to run a warm-up or main session
    based on :attr:`ConnectionState.warmup_remaining` and the elapsed
    time since the last session ended. On natural end, stashes the path
    of the freshly-written koch record on ``state`` so a subsequent
    ``save-koch-answers`` can rewrite the same file with learner answers.
    """
    try:
        timeout = load_warm_up_timeout_seconds(state.config_path)
        if state.last_session_ended_at is not None:
            elapsed = time.monotonic() - state.last_session_ended_at
            if elapsed > timeout:
                state.warmup_remaining = 2

        if state.is_fresh_set:
            state.set_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        if state.warmup_remaining > 0:
            set_session = 3 - state.warmup_remaining
            record_path = await _start_warmup_action(
                state.ws, state.config_path, set_session=set_session, set_id=state.set_id
            )
            state.warmup_remaining -= 1
        else:
            set_session = state.main_session_next
            record_path = await _start_action(
                state.ws, state.config_path, set_session=set_session, set_id=state.set_id
            )
            state.main_session_next += 1
            if state.main_session_next > 8:
                state.warmup_remaining = 2
                state.main_session_next = 3

        state.pending_koch_record_path = record_path
        state.last_session_ended_at = time.monotonic()
    except ValueError as exc:
        await _send_event(
            state.ws,
            {"type": "error", "reason": "invalid-config", "detail": str(exc)},
        )
    except asyncio.CancelledError:
        # Stop was requested — send session-end so the UI knows the
        # session is over (spec §1.5).
        await _send_event(state.ws, {"type": "session-end"})


def _reconstruct_recognition_set_state(state: ConnectionState) -> None:
    """Restore the recognition set state machine from persisted records."""
    try:
        save_directory = load_save_directory(state.config_path)
    except Exception:
        return

    records = _iter_recognition_records(save_directory)
    if not records:
        return

    by_set: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        gen = r.get("generation") or {}
        sid = gen.get("set_id")
        if isinstance(sid, str) and sid:
            by_set.setdefault(sid, []).append(r)

    if not by_set:
        return

    latest_set_id = max(by_set)
    group = by_set[latest_set_id]

    max_session = 0
    latest_ended: datetime | None = None
    for r in group:
        gen = r.get("generation") or {}
        ss = gen.get("set_session")
        if isinstance(ss, int) and not isinstance(ss, bool) and ss > max_session:
            max_session = ss
        ended = r.get("ended_at")
        if isinstance(ended, str):
            try:
                dt = datetime.fromisoformat(ended.replace("Z", "+00:00"))
                if latest_ended is None or dt > latest_ended:
                    latest_ended = dt
            except ValueError:
                continue

    if max_session == 0 or max_session >= 8 or latest_ended is None:
        return

    elapsed = (datetime.now(timezone.utc) - latest_ended).total_seconds()
    state.recognition_set_id = latest_set_id
    state.recognition_last_session_ended_at = time.monotonic() - elapsed
    state.recognition_session_next = max_session + 1


def _next_recognition_profile(state: ConnectionState, claimed: tuple[str, ...]) -> dict[str, Any]:
    if not claimed:
        return {}
    try:
        save_directory = load_save_directory(state.config_path)
        gears = _resolve_recognition_session_gears(
            save_directory,
            " ".join(sorted(claimed)),
            exercise_count=1,
            set_id=state.recognition_set_id,
            set_session=state.recognition_session_next,
        )
    except Exception:
        logger.exception("could not resolve next recognition profile")
        return {}
    gear = gears[0] if gears else 0
    return {
        "recognition_set_session": state.recognition_session_next,
        "recognition_gear": gear,
        "recognition_kind": _recognition_kind_for_gear(gear),
    }


def _next_koch_profile(state: ConnectionState, claimed: tuple[str, ...]) -> dict[str, Any]:
    if not claimed:
        return {}
    if state.warmup_remaining > 0:
        return {
            **_next_koch_set_position(state),
            "koch_gears": [0] * 5,
        }
    try:
        save_directory = load_save_directory(state.config_path)
        gears, _rst = _resolve_session_gears_and_rst(
            save_directory,
            " ".join(sorted(claimed)),
            exercise_count=5,
        )
    except Exception:
        logger.exception("could not resolve next Koch exercise profile")
        return {
            "koch_set_session": state.main_session_next,
            "koch_warm_up": False,
        }
    return {
        **_next_koch_set_position(state),
        "koch_gears": gears,
    }


def _next_koch_set_position(state: ConnectionState) -> dict[str, Any]:
    if state.warmup_remaining > 0:
        return {
            "koch_set_session": 3 - state.warmup_remaining,
            "koch_warm_up": True,
        }
    return {
        "koch_set_session": state.main_session_next,
        "koch_warm_up": False,
    }


async def _run_start_recognition_session(state: ConnectionState) -> None:
    """Wrap a recognition ``start-recognition`` with the set state machine."""
    try:
        if state.is_recognition_fresh_set:
            state.recognition_set_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        set_session = state.recognition_session_next
        recognition = await _start_recognition_action(
            state.ws,
            state.config_path,
            set_session=set_session,
            set_id=state.recognition_set_id,
            anchors_dir=state.anchors_dir,
        )
        if recognition is None:
            return
        state.recognition = recognition
        await _run_recognition_session(recognition)
        state.recognition_session_next += 1
        if state.recognition_session_next > 8:
            state.recognition_session_next = 1

        state.recognition_last_session_ended_at = time.monotonic()
        state.recognition = None
    except ValueError as exc:
        await _send_event(
            state.ws,
            {"type": "error", "reason": "invalid-config", "detail": str(exc)},
        )
    except asyncio.CancelledError:
        state.recognition = None
        await _send_event(state.ws, {"type": "session-end"})


# Bare-delegation actions: no per-slot supersede, no special state. The
# dispatch loop calls these directly. Stateful or task-owning actions
# stay as explicit branches in :func:`handler`.
_BARE_HANDLERS: dict[str, Callable[[ConnectionState, dict[str, Any]], Awaitable[None]]] = {
    "claim-symbol": lambda state, msg: _claim_symbol_action(
        state.ws,
        msg.get("symbol", ""),
        state.config_path,
        set_is_fresh=state.is_fresh_set,
        **_next_koch_set_position(state),
    ),
    "unclaim-symbol": lambda state, msg: _unclaim_symbol_action(
        state.ws,
        msg.get("symbol", ""),
        state.config_path,
        set_is_fresh=state.is_fresh_set,
        **_next_koch_set_position(state),
    ),
    "get-audio-settings": lambda state, msg: _get_audio_settings_action(
        state.ws, state.config_path
    ),
    "set-audio-settings": lambda state, msg: _set_audio_settings_action(
        state.ws, msg, state.config_path
    ),
    "get-audio-output-devices": lambda state, msg: _get_audio_output_devices_action(
        state.ws, state.config_path
    ),
    "set-audio-output-device": lambda state, msg: _set_audio_output_device_action(
        state.ws, msg, state.config_path
    ),
    "play-audio-output-test": lambda state, msg: _play_audio_output_test_action(
        state.ws, msg, state.config_path
    ),
    "get-voice-settings": lambda state, msg: _get_voice_settings_action(
        state.ws, state.config_path
    ),
    "set-voice-settings": lambda state, msg: _set_voice_settings_action(
        state.ws, msg, state.config_path
    ),
    "set-voice-input-device": lambda state, msg: _set_voice_input_device_action(
        state.ws, msg, state.config_path
    ),
    "save-test-message": lambda state, msg: _save_test_message_action(state.ws, msg),
}


async def handler(
    ws: WebSocketServerProtocol,
    config_path: Path = DEFAULT_CONFIG_PATH,
    anchors_dir: Path | None = None,
    key_note_source: KeyNoteSource | None = None,
) -> None:
    """Top-level WS connection handler. Dispatches incoming JSON commands."""
    state = ConnectionState(
        ws=ws,
        config_path=config_path,
        anchors_dir=anchors_dir if anchors_dir is not None else find_anchors_dir(),
        key_note_source=key_note_source,
    )
    _reconstruct_set_state(state)
    _reconstruct_recognition_set_state(state)

    # Push current state on connect so the UI does not need to ask.
    claimed = load_claimed_symbols(state.config_path)
    save_directory = load_save_directory(state.config_path)
    claimed_set_key = " ".join(sorted(claimed))
    evidence_ready_for_next, ready_for_next = _koch_readiness_state(save_directory, claimed_set_key)
    ready_for_next_send = _next_send_symbol_readiness(save_directory, claimed_set_key)
    await _send_event(
        ws,
        _claimed_symbols_event(
            claimed,
            evidence_ready_for_next=evidence_ready_for_next,
            ready_for_next=ready_for_next,
            ready_for_next_send=ready_for_next_send,
            set_is_fresh=state.is_fresh_set,
            **_next_koch_profile(state, claimed),
            **_next_recognition_profile(state, claimed),
        ),
    )

    try:
        async for raw in ws:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await _send_event(ws, {"type": "error", "reason": "invalid-json"})
                continue

            action = message.get("action")
            bare = _BARE_HANDLERS.get(action) if isinstance(action, str) else None
            if bare is not None:
                await bare(state, message)
                continue

            if action == "start":
                await supersede(state.session_task)
                state.pending_koch_record_path = None
                state.session_task = asyncio.create_task(_run_start_session(state))
            elif action == "start-recognition":
                await supersede(state.session_task)
                state.pending_recognition_record_path = None
                state.session_task = asyncio.create_task(_run_start_recognition_session(state))
            elif action == "start-recognition-floor":
                if state.recognition_floor_task is None or state.recognition_floor_task.done():
                    state.recognition_floor_task = asyncio.create_task(
                        _run_recognition_receiver_bed_loop(state.config_path)
                    )
            elif action == "stop":
                # session-end is sent by _run_start_session's CancelledError handler.
                if state.session_task is not None and not state.session_task.done():
                    state.session_task.cancel()
            elif action == "save-koch-answers":
                saved = await _save_koch_answers_action(ws, message, state.pending_koch_record_path)
                if saved:
                    # One save per pending record. A subsequent save
                    # without a new session-end is a no-op error.
                    state.pending_koch_record_path = None
            elif action == "save-recognition-answers":
                saved = await _save_recognition_answers_action(
                    ws, message, state.pending_recognition_record_path
                )
                if saved:
                    state.pending_recognition_record_path = None
            elif action == "complete-recognition-exercise":
                if state.recognition is None:
                    await _send_event(ws, {"type": "error", "reason": "no-active-recognition"})
                else:
                    completion = _coerce_recognition_exercise_completion(message)
                    if completion is None:
                        await _send_event(
                            ws,
                            {"type": "error", "reason": "invalid-recognition-exercise"},
                        )
                    else:
                        await state.recognition.push_completion(completion)
            elif action == "append-recognition-diagnostic":
                if state.recognition is None:
                    await _send_event(ws, {"type": "error", "reason": "no-active-recognition"})
                else:
                    diagnostic = _coerce_recognition_diagnostic(message)
                    if diagnostic is None:
                        await _send_event(
                            ws,
                            {"type": "error", "reason": "invalid-recognition-diagnostic"},
                        )
                    else:
                        state.recognition.append_late_voice_capture(
                            diagnostic["exercise_index"],
                            diagnostic["late_voice_capture"],
                        )
            elif action == "request-copy-exercises":
                # A fresh request closes any in-flight Cadence session
                # before opening a new one — we never silently merge
                # two separate rounds of keying into one record.
                state.close_active_cadence_session()
                new_session = await _request_copy_exercises_action(ws, message, state.config_path)
                if new_session is not None:
                    state.cadence = new_session
            elif action == "complete-cadence-session":
                state.close_active_cadence_session()
            elif action == "request-copy-key-exercises":
                state.close_active_copy_key_session()
                await supersede(state.copy_key_play_task)
                new_session = await _request_copy_key_exercises_action(ws, state.config_path)
                if new_session is not None:
                    state.copy_key = new_session
            elif action == "play-copy-key-exercise":
                if state.copy_key is None:
                    await _send_event(ws, {"type": "error", "reason": "no-active-copy-key-session"})
                else:
                    exercise_index = message.get("exercise_index")
                    if not isinstance(exercise_index, int) or isinstance(exercise_index, bool):
                        await _send_event(
                            ws,
                            {"type": "error", "reason": "invalid-copy-key-exercise-index"},
                        )
                    else:
                        await supersede(state.copy_key_play_task)
                        state.copy_key_play_task = asyncio.create_task(
                            _play_copy_key_exercise(ws, state.copy_key, exercise_index)
                        )
            elif action == "complete-copy-key-session":
                await supersede(state.copy_key_play_task)
                state.close_active_copy_key_session()
            elif action == "abort-copy-key-session":
                await supersede(state.copy_key_play_task)
                state.copy_key = None
            elif action == "start-key-input":
                await supersede(state.key_input_task)
                state.key_input_task = asyncio.create_task(
                    _run_key_input_action(
                        ws,
                        state.config_path,
                        state.key_note_source,
                        recorder=state.active_recorder,
                    )
                )
            elif action == "start-browser-key-input":
                await supersede(state.key_input_task)
                if state.browser is not None:
                    await state.browser.cancel_flush()
                try:
                    browser_settings = load_keyer_settings(state.config_path)
                    browser_audio_params = load_audio_parameters(state.config_path)
                except ValueError as exc:
                    await _send_event(
                        ws,
                        {"type": "error", "reason": "invalid-config", "detail": str(exc)},
                    )
                    continue
                # Calibrate browser performance.now() → server time.monotonic()
                # so event timestamps and tick() flush times share one clock.
                perf_now = message.get("perf_now")
                clock_offset: float | None = None
                if isinstance(perf_now, (int, float)) and not isinstance(perf_now, bool):
                    clock_offset = time.monotonic() - float(perf_now)
                input_name = message.get("input_name")
                if not isinstance(input_name, str) or not input_name.strip():
                    input_name = "browser MIDI"
                state.browser = BrowserKeyInputState(
                    ws=ws,
                    settings=browser_settings,
                    audio_params=browser_audio_params,
                    assembler=KeyElementAssembler(),
                    decoder=KeyDecoder(
                        dit_seconds=timing.dit_seconds(browser_audio_params.character_speed_wpm),
                        character_gap_seconds=timing.send_inter_character_seconds(
                            browser_audio_params.character_speed_wpm
                        ),
                        word_gap_seconds=timing.send_inter_word_seconds(
                            browser_audio_params.character_speed_wpm
                        ),
                    ),
                    clock_offset=clock_offset,
                    recorder=state.active_recorder,
                )
                await _send_event(
                    ws,
                    _key_input_start_payload(
                        state.browser.settings,
                        state.browser.audio_params,
                        input_name=input_name.strip(),
                        source="browser",
                    ),
                )
            elif action == "key-note-event":
                if state.browser is None:
                    await _send_event(ws, {"type": "error", "reason": "key-input-not-started"})
                    continue
                try:
                    note_event = _browser_midi_note_event(
                        message,
                        fallback_timestamp=asyncio.get_running_loop().time(),
                        clock_offset=state.browser.clock_offset,
                    )
                except ValueError as exc:
                    await _send_event(
                        ws,
                        {"type": "error", "reason": "invalid-key-event", "detail": str(exc)},
                    )
                    continue
                formed_element = await _push_key_note_event(
                    ws,
                    note_event,
                    settings=state.browser.settings,
                    audio_params=state.browser.audio_params,
                    assembler=state.browser.assembler,
                    decoder=state.browser.decoder,
                    recorder=state.active_recorder,
                )
                # Only arm the character-gap flush after a completed element
                # (note-off). On note-on we're mid-stroke; rearming the timer
                # there races the next note-off and prematurely flushes the
                # in-progress character. Cancel any pending flush instead.
                if formed_element:
                    state.browser.schedule_flush()
                else:
                    await state.browser.cancel_flush()
            elif action == "reset-key-input":
                if state.browser is not None:
                    reason = message.get("reason")
                    await state.browser.reset(reason if isinstance(reason, str) else "manual")
            elif action == "stop-key-input":
                if state.browser is not None:
                    await state.browser.cancel_flush()
                    state.browser = None
                if state.key_input_task is not None and not state.key_input_task.done():
                    state.key_input_task.cancel()
                state.close_active_cadence_session()
                state.close_active_copy_key_session()
            elif action == "play-test-message":
                await supersede(state.test_message_task)
                state.test_message_task = asyncio.create_task(
                    _play_test_message_action(ws, message)
                )
            elif action == "play-texture-preview":
                await supersede(state.texture_preview_task)
                state.texture_preview_task = asyncio.create_task(
                    _play_texture_preview_loop(ws, message, state.config_path)
                )
            elif action == "stop-texture-preview":
                await supersede(state.texture_preview_task)
                state.texture_preview_task = None
            elif action == "save-texture-preview":
                await _save_texture_preview_action(ws, message, state.config_path)
            elif action == "play-letter":
                symbol = message.get("symbol", "")
                if not isinstance(symbol, str) or len(symbol) != 1:
                    await _send_event(
                        ws, {"type": "error", "reason": "symbol-must-be-single-character"}
                    )
                    continue
                upper = symbol.upper()
                if upper not in ANCHORED_SYMBOLS:
                    await _send_event(
                        ws, {"type": "error", "reason": "unknown-letter", "symbol": upper}
                    )
                    continue
                # Awaiting the cancelled task before starting the new one
                # preserves event ordering: no overlapping letter-start frames.
                await supersede(state.letter_task)
                state.letter_task = asyncio.create_task(
                    _run_letter_sequence(ws, upper, state.config_path, state.anchors_dir)
                )
            elif action == "play-morse-repeat":
                symbol = message.get("symbol", "")
                if not isinstance(symbol, str) or len(symbol) != 1:
                    await _send_event(
                        ws, {"type": "error", "reason": "symbol-must-be-single-character"}
                    )
                    continue
                upper = symbol.upper()
                try:
                    patterns.pattern_for(upper)
                except KeyError:
                    await _send_event(
                        ws, {"type": "error", "reason": "unknown-symbol", "symbol": upper}
                    )
                    continue
                try:
                    repeats = _optional_positive_int(message.get("repeats"), "repeats")
                except ValueError as exc:
                    await _send_event(
                        ws,
                        {
                            "type": "error",
                            "reason": "invalid-morse-repeat-request",
                            "detail": str(exc),
                        },
                    )
                    continue
                if repeats is None:
                    repeats = 3
                # Share the letter_task slot so a new preview supersedes
                # any in-flight play-letter or play-morse-repeat cleanly.
                await supersede(state.letter_task)
                state.letter_task = asyncio.create_task(
                    _run_morse_repeat(ws, upper, repeats, state.config_path)
                )
            else:
                await _send_event(ws, {"type": "error", "reason": "unknown-action"})
    except ConnectionClosed:
        pass
    finally:
        for task in (
            state.session_task,
            state.letter_task,
            state.test_message_task,
            state.texture_preview_task,
            state.key_input_task,
            state.copy_key_play_task,
        ):
            if task is not None and not task.done():
                task.cancel()
        await supersede(state.recognition_floor_task)
        if state.browser is not None:
            await state.browser.cancel_flush()
        state.close_active_cadence_session()
        state.close_active_copy_key_session()
