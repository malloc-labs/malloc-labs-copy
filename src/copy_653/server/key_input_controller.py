"""Key-input WebSocket connection handling."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Callable, Protocol

from websockets.server import WebSocketServerProtocol

from copy_653.audio import timing
from copy_653.config import load_audio_parameters, load_keyer_settings
from copy_653.midi import KeyDecoder, KeyElementAssembler
from copy_653.server.connection_context import supersede
from copy_653.server.key_input_actions import (
    BrowserKeyInputState,
    KeyNoteSource,
    _push_key_note_event,
    _run_key_input_action,
)
from copy_653.server.validation import _browser_midi_note_event
from copy_653.server.wire_events import _key_input_start_payload, _send_event


class KeyInputState(Protocol):
    ws: WebSocketServerProtocol
    config_path: Path
    key_note_source: KeyNoteSource | None
    key_input_task: asyncio.Task[None] | None
    browser: BrowserKeyInputState | None


class KeyInputController:
    """Own key-input task and browser MIDI state for one connection."""

    def __init__(
        self,
        state: KeyInputState,
        *,
        recorder: Callable[[dict[str, Any]], None],
        close_send_sessions: Callable[[], None],
    ) -> None:
        self._state = state
        self._recorder = recorder
        self._close_send_sessions = close_send_sessions

    async def handle(self, action: str, message: dict[str, Any]) -> bool:
        if action == "start-key-input":
            await self.start_key_input()
        elif action == "start-browser-key-input":
            await self.start_browser_key_input(message)
        elif action == "key-note-event":
            await self.key_note_event(message)
        elif action == "reset-key-input":
            await self.reset_key_input(message)
        elif action == "stop-key-input":
            await self.stop_key_input()
        else:
            return False
        return True

    async def start_key_input(self) -> None:
        state = self._state
        await supersede(state.key_input_task)
        state.key_input_task = asyncio.create_task(
            _run_key_input_action(
                state.ws,
                state.config_path,
                state.key_note_source,
                recorder=self._recorder,
            )
        )

    async def start_browser_key_input(self, message: dict[str, Any]) -> None:
        state = self._state
        await supersede(state.key_input_task)
        if state.browser is not None:
            await state.browser.cancel_flush()
        try:
            browser_settings = load_keyer_settings(state.config_path)
            browser_audio_params = load_audio_parameters(state.config_path)
        except ValueError as exc:
            await _send_event(
                state.ws,
                {"type": "error", "reason": "invalid-config", "detail": str(exc)},
            )
            return

        perf_now = message.get("perf_now")
        clock_offset: float | None = None
        if isinstance(perf_now, (int, float)) and not isinstance(perf_now, bool):
            clock_offset = time.monotonic() - float(perf_now)
        input_name = message.get("input_name")
        if not isinstance(input_name, str) or not input_name.strip():
            input_name = "browser MIDI"

        state.browser = BrowserKeyInputState(
            ws=state.ws,
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
            recorder=self._recorder,
        )
        await _send_event(
            state.ws,
            _key_input_start_payload(
                state.browser.settings,
                state.browser.audio_params,
                input_name=input_name.strip(),
                source="browser",
            ),
        )

    async def key_note_event(self, message: dict[str, Any]) -> None:
        state = self._state
        if state.browser is None:
            await _send_event(state.ws, {"type": "error", "reason": "key-input-not-started"})
            return
        try:
            note_event = _browser_midi_note_event(
                message,
                fallback_timestamp=asyncio.get_running_loop().time(),
                clock_offset=state.browser.clock_offset,
            )
        except ValueError as exc:
            await _send_event(
                state.ws,
                {"type": "error", "reason": "invalid-key-event", "detail": str(exc)},
            )
            return
        formed_element = await _push_key_note_event(
            state.ws,
            note_event,
            settings=state.browser.settings,
            audio_params=state.browser.audio_params,
            assembler=state.browser.assembler,
            decoder=state.browser.decoder,
            recorder=self._recorder,
        )
        if formed_element:
            state.browser.schedule_flush()
        else:
            await state.browser.cancel_flush()

    async def reset_key_input(self, message: dict[str, Any]) -> None:
        state = self._state
        if state.browser is not None:
            reason = message.get("reason")
            await state.browser.reset(reason if isinstance(reason, str) else "manual")

    async def stop_key_input(self) -> None:
        state = self._state
        if state.browser is not None:
            await state.browser.cancel_flush()
            state.browser = None
        if state.key_input_task is not None and not state.key_input_task.done():
            state.key_input_task.cancel()
        self._close_send_sessions()

    async def cleanup(self) -> None:
        state = self._state
        if state.browser is not None:
            await state.browser.cancel_flush()
