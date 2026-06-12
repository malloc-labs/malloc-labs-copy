"""Cadence and Copy Key WebSocket session handling."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Protocol

from websockets.server import WebSocketServerProtocol

from copy_653.server.send_actions import (
    _play_copy_key_exercise,
    _request_copy_exercises_action,
    _request_copy_key_exercises_action,
)
from copy_653.server.connection_context import supersede
from copy_653.server.records import (
    _ActiveCadenceSession,
    _ActiveCopyKeySession,
    _finalize_cadence_session,
    _finalize_copy_key_session,
)
from copy_653.server.wire_events import _send_event


class SendState(Protocol):
    ws: WebSocketServerProtocol
    config_path: Path
    cadence: _ActiveCadenceSession | None
    copy_key: _ActiveCopyKeySession | None
    copy_key_play_task: asyncio.Task[None] | None


class SendController:
    """Own Cadence and Copy Key active sessions for one connection."""

    def __init__(self, state: SendState) -> None:
        self._state = state

    def active_recorder(self, event: dict[str, Any]) -> None:
        """Forward a key/sent event to whichever send session is active."""
        state = self._state
        if state.copy_key is not None:
            state.copy_key.record_event(event)
        elif state.cadence is not None:
            state.cadence.record_event(event)

    def close_active_cadence_session(self) -> None:
        """Persist and clear any in-flight Cadence session."""
        state = self._state
        if state.cadence is not None:
            _finalize_cadence_session(state.cadence, state.config_path)
            state.cadence = None

    def close_active_copy_key_session(self) -> None:
        """Persist and clear any in-flight Copy Key session."""
        state = self._state
        if state.copy_key is not None:
            _finalize_copy_key_session(state.copy_key, state.config_path)
            state.copy_key = None

    def close_all(self) -> None:
        self.close_active_cadence_session()
        self.close_active_copy_key_session()

    async def handle(self, action: str, message: dict[str, Any]) -> bool:
        if action == "request-copy-exercises":
            await self.request_copy_exercises(message)
        elif action == "complete-cadence-session":
            self.close_active_cadence_session()
        elif action == "request-copy-key-exercises":
            await self.request_copy_key_exercises()
        elif action == "play-copy-key-exercise":
            await self.play_copy_key_exercise(message)
        elif action == "complete-copy-key-session":
            await self.complete_copy_key_session()
        elif action == "abort-copy-key-session":
            await self.abort_copy_key_session()
        else:
            return False
        return True

    async def request_copy_exercises(self, message: dict[str, Any]) -> None:
        state = self._state
        self.close_active_cadence_session()
        new_session = await _request_copy_exercises_action(state.ws, message, state.config_path)
        if new_session is not None:
            state.cadence = new_session

    async def request_copy_key_exercises(self) -> None:
        state = self._state
        self.close_active_copy_key_session()
        await supersede(state.copy_key_play_task)
        new_session = await _request_copy_key_exercises_action(state.ws, state.config_path)
        if new_session is not None:
            state.copy_key = new_session

    async def play_copy_key_exercise(self, message: dict[str, Any]) -> None:
        state = self._state
        if state.copy_key is None:
            await _send_event(state.ws, {"type": "error", "reason": "no-active-copy-key-session"})
            return
        exercise_index = message.get("exercise_index")
        if not isinstance(exercise_index, int) or isinstance(exercise_index, bool):
            await _send_event(
                state.ws,
                {"type": "error", "reason": "invalid-copy-key-exercise-index"},
            )
            return
        await supersede(state.copy_key_play_task)
        state.copy_key_play_task = asyncio.create_task(
            _play_copy_key_exercise(state.ws, state.copy_key, exercise_index)
        )

    async def complete_copy_key_session(self) -> None:
        state = self._state
        await supersede(state.copy_key_play_task)
        self.close_active_copy_key_session()

    async def abort_copy_key_session(self) -> None:
        state = self._state
        await supersede(state.copy_key_play_task)
        state.copy_key = None
