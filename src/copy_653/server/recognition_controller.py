"""Recognition-related WebSocket connection handling."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from websockets.server import WebSocketServerProtocol

from copy_653.config import load_save_directory
from copy_653.server.connection_context import supersede
from copy_653.server.recognition_answer_actions import _save_recognition_answers_action
from copy_653.server.recognition_actions import (
    ActiveRecognitionSession,
    _audio_params_for_gear,
    _audio_params_for_recognition_set,
    _coerce_recognition_diagnostic,
    _coerce_recognition_exercise_completion,
    _recognition_kind_for_gear,
    _run_recognition_receiver_bed_loop,
    _run_recognition_session,
    _start_recognition_action,
)
from copy_653.server.records import (
    _iter_recognition_records,
    _resolve_recognition_session_gears,
)
from copy_653.server.wire_events import _send_event

logger = logging.getLogger(__name__)


class RecognitionState(Protocol):
    ws: WebSocketServerProtocol
    config_path: Path
    anchors_dir: Path
    session_task: asyncio.Task[None] | None
    recognition_floor_task: asyncio.Task[None] | None
    recognition_session_next: int
    recognition_set_id: str
    recognition_last_session_ended_at: float | None
    pending_recognition_record_path: Path | None
    recognition: ActiveRecognitionSession | None


class RecognitionController:
    """Own Recognition set and active-session state for one connection."""

    def __init__(self, state: RecognitionState) -> None:
        self._state = state

    def reconstruct_set_state(self) -> None:
        """Restore the recognition set state machine from persisted records."""
        state = self._state
        try:
            save_directory = load_save_directory(state.config_path)
        except Exception:
            return

        records = _iter_recognition_records(save_directory)
        if not records:
            return

        by_set: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            gen = record.get("generation") or {}
            set_id = gen.get("set_id")
            if isinstance(set_id, str) and set_id:
                by_set.setdefault(set_id, []).append(record)

        if not by_set:
            return

        latest_set_id = max(by_set)
        group = by_set[latest_set_id]

        max_session = 0
        latest_ended: datetime | None = None
        for record in group:
            gen = record.get("generation") or {}
            set_session = gen.get("set_session")
            if (
                isinstance(set_session, int)
                and not isinstance(set_session, bool)
                and set_session > max_session
            ):
                max_session = set_session
            ended = record.get("ended_at")
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

    def next_profile(self, claimed: tuple[str, ...]) -> dict[str, Any]:
        state = self._state
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

    async def handle(self, action: str, message: dict[str, Any]) -> bool:
        if action == "start-recognition":
            await self.start_session()
        elif action == "start-recognition-floor":
            self.start_floor()
        elif action == "save-recognition-answers":
            await self.save_answers(message)
        elif action == "complete-recognition-exercise":
            await self.complete_exercise(message)
        elif action == "append-recognition-diagnostic":
            await self.append_diagnostic(message)
        else:
            return False
        return True

    async def start_session(self) -> None:
        state = self._state
        await supersede(state.session_task)
        state.pending_recognition_record_path = None
        state.session_task = asyncio.create_task(self._run_start_session())

    def start_floor(self) -> None:
        state = self._state
        if state.recognition_floor_task is None or state.recognition_floor_task.done():
            state.recognition_floor_task = asyncio.create_task(
                _run_recognition_receiver_bed_loop(state.config_path)
            )

    async def save_answers(self, message: dict[str, Any]) -> None:
        state = self._state
        saved = await _save_recognition_answers_action(
            state.ws, message, state.pending_recognition_record_path
        )
        if saved:
            state.pending_recognition_record_path = None

    async def complete_exercise(self, message: dict[str, Any]) -> None:
        state = self._state
        if state.recognition is None:
            await _send_event(state.ws, {"type": "error", "reason": "no-active-recognition"})
            return
        completion = _coerce_recognition_exercise_completion(message)
        if completion is None:
            await _send_event(
                state.ws,
                {"type": "error", "reason": "invalid-recognition-exercise"},
            )
            return
        await state.recognition.push_completion(completion)

    async def append_diagnostic(self, message: dict[str, Any]) -> None:
        state = self._state
        if state.recognition is None:
            await _send_event(state.ws, {"type": "error", "reason": "no-active-recognition"})
            return
        diagnostic = _coerce_recognition_diagnostic(message)
        if diagnostic is None:
            await _send_event(
                state.ws,
                {"type": "error", "reason": "invalid-recognition-diagnostic"},
            )
            return
        state.recognition.append_late_voice_capture(
            diagnostic["exercise_index"],
            diagnostic["late_voice_capture"],
        )

    async def _run_start_session(self) -> None:
        state = self._state
        try:
            if state.recognition_session_next == 1:
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
            floor_params = _audio_params_for_recognition_set(
                _audio_params_for_gear(recognition.audio_params, recognition.gear),
                set_session,
            )
            await supersede(state.recognition_floor_task)
            state.recognition_floor_task = asyncio.create_task(
                _run_recognition_receiver_bed_loop(
                    state.config_path,
                    audio_params=floor_params,
                )
            )
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
