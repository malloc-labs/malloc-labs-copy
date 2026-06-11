"""Playback-related WebSocket action handling."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol

from websockets.server import WebSocketServerProtocol

from copy_653.audio import patterns
from copy_653.letters import ANCHORED_SYMBOLS
from copy_653.server.connection_context import supersede
from copy_653.server.letter_playback_actions import (
    _run_letter_sequence,
    _run_morse_repeat,
)
from copy_653.server.test_message_actions import _play_test_message_action
from copy_653.server.texture_preview_actions import (
    _play_texture_preview_loop,
    _save_texture_preview_action,
)
from copy_653.server.validation import _optional_positive_int
from copy_653.server.wire_events import _send_event


class PlaybackState(Protocol):
    ws: WebSocketServerProtocol
    config_path: Path
    anchors_dir: Path
    letter_task: asyncio.Task[None] | None
    test_message_task: asyncio.Task[None] | None
    texture_preview_task: asyncio.Task[None] | None


class PlaybackController:
    """Own playback task slots for one WebSocket connection."""

    def __init__(self, state: PlaybackState) -> None:
        self._state = state

    async def handle(self, action: str, message: dict[str, Any]) -> bool:
        if action == "play-test-message":
            await self.play_test_message(message)
        elif action == "play-texture-preview":
            await self.play_texture_preview(message)
        elif action == "stop-texture-preview":
            await self.stop_texture_preview()
        elif action == "save-texture-preview":
            await self.save_texture_preview(message)
        elif action == "play-letter":
            await self.play_letter(message)
        elif action == "play-morse-repeat":
            await self.play_morse_repeat(message)
        else:
            return False
        return True

    async def play_test_message(self, message: dict[str, Any]) -> None:
        state = self._state
        await supersede(state.test_message_task)
        state.test_message_task = asyncio.create_task(_play_test_message_action(state.ws, message))

    async def play_texture_preview(self, message: dict[str, Any]) -> None:
        state = self._state
        await supersede(state.texture_preview_task)
        state.texture_preview_task = asyncio.create_task(
            _play_texture_preview_loop(state.ws, message, state.config_path)
        )

    async def stop_texture_preview(self) -> None:
        state = self._state
        await supersede(state.texture_preview_task)
        state.texture_preview_task = None

    async def save_texture_preview(self, message: dict[str, Any]) -> None:
        state = self._state
        await _save_texture_preview_action(state.ws, message, state.config_path)

    async def play_letter(self, message: dict[str, Any]) -> None:
        state = self._state
        symbol = message.get("symbol", "")
        if not isinstance(symbol, str) or len(symbol) != 1:
            await _send_event(
                state.ws, {"type": "error", "reason": "symbol-must-be-single-character"}
            )
            return
        upper = symbol.upper()
        if upper not in ANCHORED_SYMBOLS:
            await _send_event(
                state.ws, {"type": "error", "reason": "unknown-letter", "symbol": upper}
            )
            return
        await supersede(state.letter_task)
        state.letter_task = asyncio.create_task(
            _run_letter_sequence(state.ws, upper, state.config_path, state.anchors_dir)
        )

    async def play_morse_repeat(self, message: dict[str, Any]) -> None:
        state = self._state
        symbol = message.get("symbol", "")
        if not isinstance(symbol, str) or len(symbol) != 1:
            await _send_event(
                state.ws, {"type": "error", "reason": "symbol-must-be-single-character"}
            )
            return
        upper = symbol.upper()
        try:
            patterns.pattern_for(upper)
        except KeyError:
            await _send_event(
                state.ws, {"type": "error", "reason": "unknown-symbol", "symbol": upper}
            )
            return
        try:
            repeats = _optional_positive_int(message.get("repeats"), "repeats")
        except ValueError as exc:
            await _send_event(
                state.ws,
                {
                    "type": "error",
                    "reason": "invalid-morse-repeat-request",
                    "detail": str(exc),
                },
            )
            return
        if repeats is None:
            repeats = 3
        await supersede(state.letter_task)
        state.letter_task = asyncio.create_task(
            _run_morse_repeat(state.ws, upper, repeats, state.config_path)
        )
