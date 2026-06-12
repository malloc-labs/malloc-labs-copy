"""Koch exercise WebSocket connection handling."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from websockets.server import WebSocketServerProtocol

from copy_653.config import load_save_directory, load_warm_up_timeout_seconds
from copy_653.server.claimed_symbols_actions import (
    _claim_symbol_action,
    _unclaim_symbol_action,
)
from copy_653.server.koch_actions import (
    _save_koch_answers_action,
    _start_action,
    _start_warmup_action,
)
from copy_653.server.connection_context import supersede
from copy_653.server.records import (
    _iter_koch_records,
    _resolve_session_gears_and_rst,
)
from copy_653.server.wire_events import _send_event
from copy_653.sequence.listening_conditions import (
    KOCH_CHALLENGE_END_SESSION,
    KOCH_CHALLENGE_START_SESSION,
    KOCH_PROBE_PHASE_CHALLENGE,
)

logger = logging.getLogger(__name__)


class KochState(Protocol):
    ws: WebSocketServerProtocol
    config_path: Path
    session_task: asyncio.Task[None] | None
    pending_koch_record_path: Path | None
    warmup_remaining: int
    main_session_next: int
    last_session_ended_at: float | None
    set_id: str


class KochController:
    """Own Koch set and active-session state for one connection."""

    def __init__(self, state: KochState) -> None:
        self._state = state

    @property
    def is_fresh_set(self) -> bool:
        state = self._state
        return state.warmup_remaining == 2 and state.main_session_next == 3

    def reconstruct_set_state(self) -> None:
        """Restore the Koch set state machine from persisted records."""
        state = self._state
        try:
            save_directory = load_save_directory(state.config_path)
        except Exception:
            return

        records = _iter_koch_records(save_directory)
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

        if max_session == 0 or max_session >= KOCH_CHALLENGE_END_SESSION or latest_ended is None:
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

    def next_set_position(self) -> dict[str, Any]:
        state = self._state
        if state.warmup_remaining > 0:
            return {
                "koch_set_session": 3 - state.warmup_remaining,
                "koch_warm_up": True,
            }
        return {
            "koch_set_session": state.main_session_next,
            "koch_warm_up": False,
        }

    def next_profile(self, claimed: tuple[str, ...]) -> dict[str, Any]:
        state = self._state
        if not claimed:
            return {}
        if state.warmup_remaining > 0:
            return {
                **self.next_set_position(),
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
        profile = {
            **self.next_set_position(),
            "koch_gears": gears,
        }
        if KOCH_CHALLENGE_START_SESSION <= state.main_session_next <= KOCH_CHALLENGE_END_SESSION:
            profile["probe_phase"] = KOCH_PROBE_PHASE_CHALLENGE
        return profile

    async def handle(self, action: str, message: dict[str, Any]) -> bool:
        if action == "start":
            await self.start_session()
        elif action == "save-koch-answers":
            await self.save_answers(message)
        elif action == "claim-symbol":
            await self.claim_symbol(message)
        elif action == "unclaim-symbol":
            await self.unclaim_symbol(message)
        else:
            return False
        return True

    async def start_session(self) -> None:
        state = self._state
        await supersede(state.session_task)
        state.pending_koch_record_path = None
        state.session_task = asyncio.create_task(self._run_start_session())

    async def save_answers(self, message: dict[str, Any]) -> None:
        state = self._state
        saved = await _save_koch_answers_action(state.ws, message, state.pending_koch_record_path)
        if saved:
            state.pending_koch_record_path = None

    async def claim_symbol(self, message: dict[str, Any]) -> None:
        state = self._state
        await _claim_symbol_action(
            state.ws,
            message.get("symbol", ""),
            state.config_path,
            set_is_fresh=self.is_fresh_set,
            **self.next_set_position(),
        )

    async def unclaim_symbol(self, message: dict[str, Any]) -> None:
        state = self._state
        await _unclaim_symbol_action(
            state.ws,
            message.get("symbol", ""),
            state.config_path,
            set_is_fresh=self.is_fresh_set,
            **self.next_set_position(),
        )

    async def _run_start_session(self) -> None:
        """Wrap a `start` action with the Koch set state machine."""
        state = self._state
        try:
            timeout = load_warm_up_timeout_seconds(state.config_path)
            if state.last_session_ended_at is not None:
                elapsed = time.monotonic() - state.last_session_ended_at
                if elapsed > timeout:
                    state.warmup_remaining = 2

            if self.is_fresh_set:
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
                if state.main_session_next > KOCH_CHALLENGE_END_SESSION:
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
            await _send_event(state.ws, {"type": "session-end"})
