"""Claimed-symbol WebSocket actions."""

from __future__ import annotations

import logging
from pathlib import Path

from websockets.server import WebSocketServerProtocol

from copy_653.audio import patterns
from copy_653.config import (
    load_claimed_symbols,
    load_save_directory,
    save_claimed_symbols,
)
from copy_653.server.records import (
    _koch_readiness_state,
    _next_send_symbol_readiness,
    _recognition_readiness_state,
    _resolve_session_gears_and_rst,
)
from copy_653.server.wire_events import _claimed_symbols_event, _send_event

logger = logging.getLogger(__name__)


async def _broadcast_claimed_state(
    ws: WebSocketServerProtocol,
    claimed: tuple[str, ...],
    config_path: Path,
    *,
    set_is_fresh: bool,
    koch_set_session: int | None = None,
    koch_gears: list[int] | None = None,
    koch_warm_up: bool | None = None,
) -> None:
    """Resolve readiness signals and push the claimed-symbols event."""
    save_directory = load_save_directory(config_path)
    claimed_set_key = " ".join(sorted(claimed))
    recent_ready_for_next, settled_ready_for_next = _recognition_readiness_state(
        save_directory, claimed_set_key
    )
    evidence_ready_for_next, ready_for_next = _koch_readiness_state(save_directory, claimed_set_key)
    ready_for_next_send = _next_send_symbol_readiness(save_directory, claimed_set_key)
    if koch_gears is None and koch_set_session is not None:
        if koch_warm_up:
            koch_gears = [0] * 5
        else:
            try:
                koch_gears, _rst = _resolve_session_gears_and_rst(
                    save_directory, claimed_set_key, exercise_count=5
                )
            except Exception:
                logger.exception("could not resolve next Koch exercise profile")
    await _send_event(
        ws,
        _claimed_symbols_event(
            claimed,
            recent_ready_for_next=recent_ready_for_next,
            settled_ready_for_next=settled_ready_for_next,
            evidence_ready_for_next=evidence_ready_for_next,
            ready_for_next=ready_for_next,
            ready_for_next_send=ready_for_next_send,
            set_is_fresh=set_is_fresh,
            koch_set_session=koch_set_session,
            koch_gears=koch_gears,
            koch_warm_up=koch_warm_up,
        ),
    )


async def _claim_symbol_action(
    ws: WebSocketServerProtocol,
    symbol: str,
    config_path: Path,
    *,
    set_is_fresh: bool = True,
    koch_set_session: int | None = None,
    koch_gears: list[int] | None = None,
    koch_warm_up: bool | None = None,
) -> None:
    """Append ``symbol`` to the claimed set and broadcast the new state.

    Idempotent: claiming a symbol already in the set is a no-op (still
    rebroadcasts, so a UI out of sync converges).

    Validation per spec §1.5: an unknown symbol surfaces as an
    ``error`` event without mutating the config.
    """
    if not isinstance(symbol, str) or len(symbol) != 1:
        await _send_event(ws, {"type": "error", "reason": "symbol-must-be-single-character"})
        return

    upper = symbol.upper()
    try:
        patterns.pattern_for(upper)
    except KeyError:
        await _send_event(ws, {"type": "error", "reason": "unknown-symbol", "symbol": upper})
        return

    claimed = load_claimed_symbols(config_path)
    if upper not in claimed:
        new_claimed = (*claimed, upper)
        save_claimed_symbols(new_claimed, config_path)
        claimed = new_claimed

    await _broadcast_claimed_state(
        ws,
        claimed,
        config_path,
        set_is_fresh=set_is_fresh,
        koch_set_session=koch_set_session,
        koch_gears=koch_gears,
        koch_warm_up=koch_warm_up,
    )


async def _unclaim_symbol_action(
    ws: WebSocketServerProtocol,
    symbol: str,
    config_path: Path,
    *,
    set_is_fresh: bool = True,
    koch_set_session: int | None = None,
    koch_gears: list[int] | None = None,
    koch_warm_up: bool | None = None,
) -> None:
    """Remove ``symbol`` from the claimed set and broadcast the new state.

    Idempotent: unclaiming a symbol not in the set is a no-op (still
    rebroadcasts, so a UI out of sync converges).

    The first two symbols in KOCH_ORDER (K, M) are the permanent starting
    pair and cannot be unclaimed — the engine requires at least two symbols
    to generate a session. Attempting to unclaim them surfaces an error.
    """
    if not isinstance(symbol, str) or len(symbol) != 1:
        await _send_event(ws, {"type": "error", "reason": "symbol-must-be-single-character"})
        return

    upper = symbol.upper()
    if upper in (patterns.KOCH_ORDER[0], patterns.KOCH_ORDER[1]):
        await _send_event(
            ws, {"type": "error", "reason": "cannot-unclaim-starting-pair", "symbol": upper}
        )
        return

    claimed = load_claimed_symbols(config_path)
    if upper in claimed:
        new_claimed = tuple(s for s in claimed if s != upper)
        save_claimed_symbols(new_claimed, config_path)
        claimed = new_claimed

    await _broadcast_claimed_state(
        ws,
        claimed,
        config_path,
        set_is_fresh=set_is_fresh,
        koch_set_session=koch_set_session,
        koch_gears=koch_gears,
        koch_warm_up=koch_warm_up,
    )
