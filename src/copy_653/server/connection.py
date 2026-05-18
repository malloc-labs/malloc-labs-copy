"""Per-connection state and the WS dispatch loop.

One :class:`ConnectionState` lives per WS connection (one browser tab).
It owns the four per-slot task references (session / letter / test
message / key input), the optional browser-key-input state, and the
optional active Cadence session.

Stateless action coroutines live in :mod:`copy_653.server.actions`;
this module is the only caller of them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol

from copy_653.audio import patterns, timing
from copy_653.audio.parameters import AudioParameters
from copy_653.config import (
    DEFAULT_CONFIG_PATH,
    KeyerSettings,
    load_audio_parameters,
    load_claimed_symbols,
    load_keyer_settings,
)
from copy_653.letters import ANCHORED_SYMBOLS, find_anchors_dir
from copy_653.midi import KeyDecoder, KeyElementAssembler
from copy_653.server.actions import (
    KeyNoteSource,
    _claim_symbol_action,
    _flush_key_symbol,
    _get_audio_settings_action,
    _play_test_message_action,
    _push_key_note_event,
    _request_copy_exercises_action,
    _run_key_input_action,
    _run_letter_sequence,
    _run_morse_repeat,
    _save_test_message_action,
    _set_audio_settings_action,
    _start_action,
    _unclaim_symbol_action,
)
from copy_653.server.records import _ActiveCadenceSession, _finalize_cadence_session
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
class BrowserKeyInputState:
    """In-flight state for a browser MIDI key-input session.

    Created on ``start-browser-key-input``, retired on ``stop-key-input``
    or socket close. Owns its own per-character-gap flush task so a
    pending flush is cancelled cleanly when the state retires.
    """

    ws: WebSocketServerProtocol
    settings: KeyerSettings
    audio_params: AudioParameters
    assembler: KeyElementAssembler
    decoder: KeyDecoder
    # Offset from browser performance.now() (seconds) to server
    # time.monotonic() (seconds), captured once per session so element
    # timestamps and timer-driven flushes share one clock domain.
    clock_offset: float | None = None
    flush_task: asyncio.Task[None] | None = None
    # Forwarded to the timer-driven flush so symbols finalised by
    # silence (the common case) reach the Cadence record alongside
    # symbols finalised by the next stroke's gap-in-push.
    recorder: Callable[[dict[str, Any]], None] | None = None

    async def cancel_flush(self) -> None:
        if self.flush_task is not None and not self.flush_task.done():
            self.flush_task.cancel()
            try:
                await self.flush_task
            except asyncio.CancelledError:
                pass
        self.flush_task = None

    def schedule_flush(self) -> None:
        if self.flush_task is not None and not self.flush_task.done():
            self.flush_task.cancel()

        async def _flush_after_gap() -> None:
            await asyncio.sleep(
                timing.send_inter_character_seconds(self.audio_params.character_speed_wpm)
            )
            await _flush_key_symbol(self.ws, self.decoder, self.recorder)

        self.flush_task = asyncio.create_task(_flush_after_gap())

    async def reset(self, reason: str) -> None:
        await self.cancel_flush()
        self.assembler = KeyElementAssembler()
        self.decoder.reset()
        await _send_event(self.ws, {"type": "key-input-reset", "reason": reason})


@dataclass
class ConnectionState:
    """All per-WS-connection state.

    Owns four per-slot task references (session, letter, test-message,
    key-input), the optional browser-key-input state, and the optional
    active Cadence session. The dispatch loop in :func:`handler` is the
    only mutator.
    """

    ws: WebSocketServerProtocol
    config_path: Path
    anchors_dir: Path
    key_note_source: KeyNoteSource | None = None
    session_task: asyncio.Task[None] | None = None
    letter_task: asyncio.Task[None] | None = None
    test_message_task: asyncio.Task[None] | None = None
    key_input_task: asyncio.Task[None] | None = None
    browser: BrowserKeyInputState | None = None
    cadence: _ActiveCadenceSession | None = None

    def cadence_recorder(self, event: dict[str, Any]) -> None:
        """Forward an outbound key/sent event to the active Cadence record."""
        if self.cadence is not None:
            self.cadence.record_event(event)

    def close_active_cadence_session(self) -> None:
        """Persist and clear any in-flight Cadence session."""
        if self.cadence is not None:
            _finalize_cadence_session(self.cadence, self.config_path)
            self.cadence = None


async def _run_start_session(
    ws: WebSocketServerProtocol,
    config_path: Path,
) -> None:
    """Wrap a `start` action with the common invalid-config and
    stop-was-requested handlers."""
    try:
        await _start_action(ws, config_path)
    except ValueError as exc:
        await _send_event(
            ws,
            {"type": "error", "reason": "invalid-config", "detail": str(exc)},
        )
    except asyncio.CancelledError:
        # Stop was requested — send session-end so the UI knows the
        # session is over (spec §1.5).
        await _send_event(ws, {"type": "session-end"})


# Bare-delegation actions: no per-slot supersede, no special state. The
# dispatch loop calls these directly. Stateful or task-owning actions
# stay as explicit branches in :func:`handler`.
_BARE_HANDLERS: dict[str, Callable[[ConnectionState, dict[str, Any]], Awaitable[None]]] = {
    "claim-symbol": lambda state, msg: _claim_symbol_action(
        state.ws, msg.get("symbol", ""), state.config_path
    ),
    "unclaim-symbol": lambda state, msg: _unclaim_symbol_action(
        state.ws, msg.get("symbol", ""), state.config_path
    ),
    "get-audio-settings": lambda state, msg: _get_audio_settings_action(
        state.ws, state.config_path
    ),
    "set-audio-settings": lambda state, msg: _set_audio_settings_action(
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

    # Push current state on connect so the UI does not need to ask.
    claimed = load_claimed_symbols(state.config_path)
    await _send_event(ws, _claimed_symbols_event(claimed))

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
                state.session_task = asyncio.create_task(
                    _run_start_session(ws, state.config_path)
                )
            elif action == "stop":
                # session-end is sent by _run_start_session's CancelledError handler.
                if state.session_task is not None and not state.session_task.done():
                    state.session_task.cancel()
            elif action == "request-copy-exercises":
                # A fresh request closes any in-flight Cadence session
                # before opening a new one — we never silently merge
                # two separate rounds of keying into one record.
                state.close_active_cadence_session()
                new_session = await _request_copy_exercises_action(ws, message, state.config_path)
                if new_session is not None:
                    state.cadence = new_session
            elif action == "start-key-input":
                await supersede(state.key_input_task)
                state.key_input_task = asyncio.create_task(
                    _run_key_input_action(
                        ws,
                        state.config_path,
                        state.key_note_source,
                        recorder=state.cadence_recorder,
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
                    recorder=state.cadence_recorder,
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
                    recorder=state.cadence_recorder,
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
            elif action == "play-test-message":
                await supersede(state.test_message_task)
                state.test_message_task = asyncio.create_task(
                    _play_test_message_action(ws, message)
                )
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
        # Connection closing — cancel any orphan tasks so playback stops
        # when the learner closes the tab.
        for task in (
            state.session_task,
            state.letter_task,
            state.test_message_task,
            state.key_input_task,
        ):
            if task is not None and not task.done():
                task.cancel()
        if state.browser is not None:
            await state.browser.cancel_flush()
        # Persist any in-flight Cadence session before the connection
        # disappears. The learner may have closed the tab mid-keying.
        state.close_active_cadence_session()
