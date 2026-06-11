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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol

from copy_653.config import (
    DEFAULT_CONFIG_PATH,
    load_claimed_symbols,
    load_save_directory,
)
from copy_653.letters import find_anchors_dir
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
from copy_653.server.connection_context import supersede
from copy_653.server.key_input_actions import (
    BrowserKeyInputState,
    KeyNoteSource,
)
from copy_653.server.key_input_controller import KeyInputController
from copy_653.server.test_message_actions import (
    _save_test_message_action,
)
from copy_653.server.playback_controller import PlaybackController
from copy_653.server.recognition_actions import (
    ActiveRecognitionSession,
)
from copy_653.server.koch_controller import KochController
from copy_653.server.recognition_controller import RecognitionController
from copy_653.server.records import (
    _ActiveCadenceSession,
    _ActiveCopyKeySession,
    _koch_readiness_state,
    _next_send_symbol_readiness,
    _recognition_readiness_state,
)
from copy_653.server.send_controller import SendController
from copy_653.server.wire_events import (
    _claimed_symbols_event,
    _send_event,
)


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
    # Koch exercise set state machine. A set is 12 sessions: 2 warm-up
    # (pair recognition), 6 main (full-burden), then 4 challenge-block
    # listening-condition probes. The warm-up re-engages when the gap
    # since the last session exceeds the configured timeout, but the
    # main/challenge counter resumes where it was.
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


# Bare-delegation actions: no per-slot supersede, no special state. The
# dispatch loop calls these directly. Stateful or task-owning actions
# stay as explicit branches in :func:`handler`.
_BARE_HANDLERS: dict[str, Callable[[ConnectionState, dict[str, Any]], Awaitable[None]]] = {
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
    koch = KochController(state)
    koch.reconstruct_set_state()
    recognition = RecognitionController(state)
    recognition.reconstruct_set_state()
    playback = PlaybackController(state)
    send = SendController(state)
    key_input = KeyInputController(
        state,
        recorder=send.active_recorder,
        close_send_sessions=send.close_all,
    )
    controllers = (koch, recognition, send, key_input, playback)

    # Push current state on connect so the UI does not need to ask.
    claimed = load_claimed_symbols(state.config_path)
    save_directory = load_save_directory(state.config_path)
    claimed_set_key = " ".join(sorted(claimed))
    recent_ready_for_next, settled_ready_for_next = _recognition_readiness_state(
        save_directory, claimed_set_key
    )
    evidence_ready_for_next, ready_for_next = _koch_readiness_state(save_directory, claimed_set_key)
    ready_for_next_send = _next_send_symbol_readiness(save_directory, claimed_set_key)
    await _send_event(
        ws,
        _claimed_symbols_event(
            claimed,
            recent_ready_for_next=recent_ready_for_next,
            settled_ready_for_next=settled_ready_for_next,
            evidence_ready_for_next=evidence_ready_for_next,
            ready_for_next=ready_for_next,
            ready_for_next_send=ready_for_next_send,
            set_is_fresh=koch.is_fresh_set,
            **koch.next_profile(claimed),
            **recognition.next_profile(claimed),
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

            if action == "stop":
                # session-end is sent by _run_start_session's CancelledError handler.
                if state.session_task is not None and not state.session_task.done():
                    state.session_task.cancel()
                continue

            if isinstance(action, str):
                handled = False
                for controller in controllers:
                    if await controller.handle(action, message):
                        handled = True
                        break
                if handled:
                    continue

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
        await key_input.cleanup()
        send.close_all()
