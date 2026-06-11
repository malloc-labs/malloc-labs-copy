"""Estimated-time projections for Recognition burden profiles."""

from __future__ import annotations

from datetime import datetime
from math import ceil
from typing import Any

from copy_653.audio import patterns

ESTIMATED_TIME_VERSION = "recognition-estimated-time-v1"
RECOGNITION_TARGET_FRACTION = 0.90
SETTLED_FUTURE_ACCURACY_LOW = 0.96
SETTLED_FUTURE_ACCURACY_HIGH = 0.98


def recognition_estimated_time(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    symbol_inventory: dict[str, Any],
    window_size: int,
) -> dict[str, Any]:
    sessions = [_recognition_session_summary(record) for record in records]
    sessions = [session for session in sessions if session["total"] > 0]
    sessions.sort(key=lambda session: session["started_at"])
    recent = sessions[-window_size:] if window_size > 0 else []
    pace_source = recent or sessions

    correct = sum(session["correct"] for session in sessions)
    total = sum(session["total"] for session in sessions)
    practice_seconds = round(sum(session["duration_seconds"] for session in sessions), 3)
    seconds_per_session = _average(
        [session["duration_seconds"] for session in pace_source if session["duration_seconds"] > 0]
    )
    slots_per_session = _average([session["total"] for session in pace_source])
    recent_correct = sum(session["correct"] for session in recent)
    recent_total = sum(session["total"] for session in recent)
    recent_fraction = _fraction(recent_correct, recent_total)

    symbols = symbol_inventory.get("symbols") if isinstance(symbol_inventory, dict) else []
    symbol_rows = [row for row in symbols if isinstance(row, dict)]
    symbol_count = max(1, len(symbol_rows))
    fallback_symbol_slots = (slots_per_session or 0.0) / symbol_count

    return {
        "version": ESTIMATED_TIME_VERSION,
        "next_symbol": patterns.next_koch_after(str(symbol) for symbol in claimed_set_key.split()),
        "target_fraction": RECOGNITION_TARGET_FRACTION,
        "current": {
            "sessions": len(sessions),
            "practice_seconds": practice_seconds,
            "correct": correct,
            "total": total,
            "fraction": _round_or_none(_fraction(correct, total)),
        },
        "pace": {
            "window_sessions": len(pace_source),
            "seconds_per_session": _round_or_none(seconds_per_session),
            "slots_per_session": _round_or_none(slots_per_session),
            "recent_fraction": _round_or_none(recent_fraction),
        },
        "estimates": [
            _estimate_slots_goal(
                "aggregate_90_recent",
                "Aggregate Recognition to 90%",
                correct=correct,
                total=total,
                future_accuracy=recent_fraction,
                slots_per_session=slots_per_session,
                seconds_per_session=seconds_per_session,
                practice_seconds=practice_seconds,
            ),
            _estimate_slots_goal(
                "aggregate_90_best",
                "Aggregate Recognition to 90% - perfect floor",
                correct=correct,
                total=total,
                future_accuracy=1.0,
                slots_per_session=slots_per_session,
                seconds_per_session=seconds_per_session,
                practice_seconds=practice_seconds,
            ),
            _estimate_claimed_symbols_goal(
                "claimed_symbols_90_best",
                "Claimed symbols all 90% - perfect floor",
                symbol_rows=symbol_rows,
                future_accuracy=1.0,
                pace_window_sessions=len(pace_source),
                fallback_symbol_slots_per_session=fallback_symbol_slots,
                seconds_per_session=seconds_per_session,
                practice_seconds=practice_seconds,
            ),
            _estimate_claimed_symbols_range(
                symbol_rows=symbol_rows,
                pace_window_sessions=len(pace_source),
                fallback_symbol_slots_per_session=fallback_symbol_slots,
                seconds_per_session=seconds_per_session,
                practice_seconds=practice_seconds,
            ),
        ],
    }


def _recognition_session_summary(record: dict[str, Any]) -> dict[str, Any]:
    correct = 0
    total = 0
    exercises = record.get("exercises")
    if isinstance(exercises, list):
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("has_evidence") is not True:
                continue
            slots = analysis.get("slots")
            if not isinstance(slots, list):
                continue
            for slot in slots:
                if not isinstance(slot, dict) or not slot.get("truth"):
                    continue
                outcome = slot.get("outcome")
                total += 1
                if outcome in {"correct", "caught_correct"}:
                    correct += 1
    return {
        "started_at": str(record.get("started_at") or ""),
        "duration_seconds": _record_duration_seconds(record),
        "correct": correct,
        "total": total,
    }


def _record_duration_seconds(record: dict[str, Any]) -> float:
    started = _parse_record_datetime(record.get("started_at"))
    ended = _parse_record_datetime(record.get("ended_at"))
    if started is None or ended is None:
        return 0.0
    seconds = (ended - started).total_seconds()
    if seconds <= 0 or seconds > 3600:
        return 0.0
    return seconds


def _parse_record_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _estimate_slots_goal(
    key: str,
    label: str,
    *,
    correct: int,
    total: int,
    future_accuracy: float,
    slots_per_session: float,
    seconds_per_session: float,
    practice_seconds: float,
) -> dict[str, Any]:
    slots_needed = _future_slots_needed(
        correct=correct,
        total=total,
        target=RECOGNITION_TARGET_FRACTION,
        future_accuracy=future_accuracy,
    )
    return _estimate_from_slots(
        key,
        label,
        slots_needed=slots_needed,
        future_accuracy=future_accuracy,
        slots_per_session=slots_per_session,
        seconds_per_session=seconds_per_session,
        practice_seconds=practice_seconds,
    )


def _estimate_claimed_symbols_goal(
    key: str,
    label: str,
    *,
    symbol_rows: list[dict[str, Any]],
    future_accuracy: float,
    pace_window_sessions: int,
    fallback_symbol_slots_per_session: float,
    seconds_per_session: float,
    practice_seconds: float,
) -> dict[str, Any]:
    sessions_needed = 0
    blocking_symbol = None
    for row in symbol_rows:
        slots_needed = _future_slots_needed(
            correct=_coerce_int(row.get("lifetime_correct"), 0),
            total=_coerce_int(row.get("lifetime_exposures"), 0),
            target=RECOGNITION_TARGET_FRACTION,
            future_accuracy=future_accuracy,
        )
        if slots_needed is None:
            return {
                "key": key,
                "label": label,
                "status": "not_trending",
                "future_accuracy": _round_or_none(future_accuracy),
                "blocking_symbol": row.get("symbol") or None,
            }
        symbol_slots_per_session = _number_like(row.get("recent_exposures")) / max(
            1, pace_window_sessions
        )
        if symbol_slots_per_session <= 0:
            symbol_slots_per_session = fallback_symbol_slots_per_session
        symbol_sessions = _sessions_from_slots(slots_needed, symbol_slots_per_session)
        if symbol_sessions > sessions_needed:
            sessions_needed = symbol_sessions
            blocking_symbol = row.get("symbol") or None

    return _estimate_from_sessions(
        key,
        label,
        sessions_needed=sessions_needed,
        future_accuracy=future_accuracy,
        seconds_per_session=seconds_per_session,
        practice_seconds=practice_seconds,
        blocking_symbol=blocking_symbol,
    )


def _estimate_claimed_symbols_range(
    *,
    symbol_rows: list[dict[str, Any]],
    pace_window_sessions: int,
    fallback_symbol_slots_per_session: float,
    seconds_per_session: float,
    practice_seconds: float,
) -> dict[str, Any]:
    low = _estimate_claimed_symbols_goal(
        "claimed_symbols_90_settled_low",
        "Claimed symbols all 90%",
        symbol_rows=symbol_rows,
        future_accuracy=SETTLED_FUTURE_ACCURACY_LOW,
        pace_window_sessions=pace_window_sessions,
        fallback_symbol_slots_per_session=fallback_symbol_slots_per_session,
        seconds_per_session=seconds_per_session,
        practice_seconds=practice_seconds,
    )
    high = _estimate_claimed_symbols_goal(
        "claimed_symbols_90_settled_high",
        "Claimed symbols all 90%",
        symbol_rows=symbol_rows,
        future_accuracy=SETTLED_FUTURE_ACCURACY_HIGH,
        pace_window_sessions=pace_window_sessions,
        fallback_symbol_slots_per_session=fallback_symbol_slots_per_session,
        seconds_per_session=seconds_per_session,
        practice_seconds=practice_seconds,
    )
    return {
        "key": "claimed_symbols_90_settled_range",
        "label": "Claimed symbols all 90%",
        "status": "estimated",
        "assumption": "future_accuracy_96_98",
        "future_accuracy_low": SETTLED_FUTURE_ACCURACY_LOW,
        "future_accuracy_high": SETTLED_FUTURE_ACCURACY_HIGH,
        "sessions_low": high.get("sessions"),
        "sessions_high": low.get("sessions"),
        "seconds_low": high.get("seconds"),
        "seconds_high": low.get("seconds"),
        "total_seconds_low": high.get("total_seconds"),
        "total_seconds_high": low.get("total_seconds"),
        "blocking_symbol": low.get("blocking_symbol") or high.get("blocking_symbol"),
    }


def _estimate_from_slots(
    key: str,
    label: str,
    *,
    slots_needed: int | None,
    future_accuracy: float,
    slots_per_session: float,
    seconds_per_session: float,
    practice_seconds: float,
) -> dict[str, Any]:
    if slots_needed is None:
        return {
            "key": key,
            "label": label,
            "status": "not_trending",
            "future_accuracy": _round_or_none(future_accuracy),
        }
    return _estimate_from_sessions(
        key,
        label,
        sessions_needed=_sessions_from_slots(slots_needed, slots_per_session),
        future_accuracy=future_accuracy,
        seconds_per_session=seconds_per_session,
        practice_seconds=practice_seconds,
    )


def _estimate_from_sessions(
    key: str,
    label: str,
    *,
    sessions_needed: int,
    future_accuracy: float,
    seconds_per_session: float,
    practice_seconds: float,
    blocking_symbol: Any = None,
) -> dict[str, Any]:
    seconds = round(max(0, sessions_needed) * max(0.0, seconds_per_session), 3)
    estimate = {
        "key": key,
        "label": label,
        "status": "already_met" if sessions_needed <= 0 else "estimated",
        "future_accuracy": _round_or_none(future_accuracy),
        "sessions": max(0, sessions_needed),
        "seconds": seconds,
        "total_seconds": round(practice_seconds + seconds, 3),
    }
    if blocking_symbol:
        estimate["blocking_symbol"] = blocking_symbol
    return estimate


def _future_slots_needed(
    *,
    correct: int,
    total: int,
    target: float,
    future_accuracy: float,
) -> int | None:
    if total <= 0:
        return 0
    if _fraction(correct, total) >= target:
        return 0
    if future_accuracy <= target:
        return None
    projected = ((target * total) - correct) / (future_accuracy - target)
    return max(0, ceil(projected - 1e-9))


def _sessions_from_slots(slots_needed: int, slots_per_session: float) -> int:
    if slots_needed <= 0:
        return 0
    if slots_per_session <= 0:
        return 0
    return ceil(slots_needed / slots_per_session)


def _average(values: list[float]) -> float:
    values = [float(value) for value in values if isinstance(value, (int, float))]
    if not values:
        return 0.0
    return sum(values) / len(values)


def _number_like(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _fraction(correct: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, correct / total))


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)
