"""Symbol inventory and readiness analysis for burden profiles."""

from __future__ import annotations

from collections import Counter
from collections import defaultdict
from typing import Any

from copy_653.audio import patterns
from copy_653.sequence.exercise_analysis import (
    LOW_FRACTION,
    STRONG_FRACTION,
    _align,
    _symbols_only,
    record_claimed_set_key,
    strip_fixed_anchor,
)

DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE = 20
RECOGNITION_TARGET_FRACTION = 0.90
RECENT_READY_TARGET_FRACTION = 0.95
RECENT_READY_MIN_SYMBOL_EXPOSURES = 50
SETTLED_READY_TARGET_FRACTION = RECOGNITION_TARGET_FRACTION

DEBT_LOW = "low"
DEBT_MODERATE = "moderate"
DEBT_HIGH = "high"
DEBT_UNKNOWN = "unknown"

CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE = 8
MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE = 20
SETTLED_READY_MIN_SYMBOL_EXPOSURES = MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE
MIN_SYMBOL_RECENT_EXPOSURES_SIGNAL = 8


def recognition_next_symbol_readiness(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE,
) -> dict[str, Any]:
    """Return recent and settled listen-side readiness for the next symbol."""
    claimed_symbols = set(claimed_set_key.split())
    if not claimed_symbols:
        return {
            "recent_ready": False,
            "settled_ready": False,
            "reason": "empty_claimed_set",
            "symbols": [],
        }

    matching = matching_recognition_records(records, claimed_set_key)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    recent = matching[: max(0, window_size)]

    stats = collect_symbol_stats(matching, symbols=claimed_symbols)
    recent_stats = collect_symbol_stats(recent, symbols=claimed_symbols)
    rows = symbol_rows_from_stats(stats, recent_stats)
    observed_symbols = {str(row.get("symbol")) for row in rows}
    if observed_symbols != claimed_symbols:
        return {
            "recent_ready": False,
            "settled_ready": False,
            "reason": "missing_symbol_evidence",
            "symbols": rows,
        }

    recent_correct = sum(_coerce_int(row.get("recent_correct"), 0) for row in rows)
    recent_total = sum(_coerce_int(row.get("recent_exposures"), 0) for row in rows)
    recent_fraction = _fraction(recent_correct, recent_total)

    recent_ready = (
        recent_total > 0
        and recent_fraction >= RECENT_READY_TARGET_FRACTION
        and all(
            _coerce_int(row.get("recent_exposures"), 0) >= RECENT_READY_MIN_SYMBOL_EXPOSURES
            and float(row.get("recent_fraction") or 0.0) >= RECENT_READY_TARGET_FRACTION
            for row in rows
        )
    )
    settled_ready = all(
        _coerce_int(row.get("lifetime_exposures"), 0) >= SETTLED_READY_MIN_SYMBOL_EXPOSURES
        and float(row.get("lifetime_fraction") or 0.0) >= SETTLED_READY_TARGET_FRACTION
        for row in rows
    )

    return {
        "recent_ready": recent_ready,
        "settled_ready": settled_ready,
        "reason": "ready" if recent_ready else "below_recent_threshold",
        "recent_fraction": round(recent_fraction, 6),
        "recent_correct": recent_correct,
        "recent_total": recent_total,
        "symbols": rows,
    }


def collect_symbol_stats(
    records: list[dict[str, Any]],
    *,
    symbols: set[str],
) -> dict[str, Any]:
    symbol_slots: dict[str, Counter[str]] = defaultdict(Counter)
    introduced_at: dict[str, str] = {}

    for record in sorted(
        recognition_records(records), key=lambda r: str(r.get("started_at") or "")
    ):
        started_at = str(record.get("started_at") or "")
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
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
                if not isinstance(slot, dict):
                    continue
                truth = slot.get("truth")
                outcome = slot.get("outcome")
                if not isinstance(truth, str) or not truth or not isinstance(outcome, str):
                    continue
                symbol = truth.upper()
                if symbols and symbol not in symbols:
                    continue
                symbol_slots[symbol][outcome] += 1
                introduced_at.setdefault(symbol, started_at)

    return {
        "symbol_slots": symbol_slots,
        "introduced_at": introduced_at,
    }


def collect_koch_symbol_stats(
    records: list[dict[str, Any]],
    *,
    symbols: set[str],
) -> dict[str, Any]:
    symbol_slots: dict[str, Counter[str]] = defaultdict(Counter)
    introduced_at: dict[str, str] = {}

    for record in sorted(records, key=lambda r: str(r.get("started_at") or "")):
        started_at = str(record.get("started_at") or "")
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("saved") is not True:
                continue
            played = str(exercise.get("played") or "")
            answer = str(exercise.get("answer") or "")
            truth = _symbols_only(strip_fixed_anchor(played))
            typed = _symbols_only(strip_fixed_anchor(answer))
            if not truth:
                continue
            for op, truth_symbol, _typed_symbol in _align(truth, typed):
                if not truth_symbol:
                    continue
                symbol = truth_symbol.upper()
                if symbols and symbol not in symbols:
                    continue
                if op == "match":
                    outcome = "correct"
                elif op == "sub":
                    outcome = "substitution"
                elif op == "del":
                    outcome = "miss"
                else:
                    continue
                symbol_slots[symbol][outcome] += 1
                introduced_at.setdefault(symbol, started_at)

    return {
        "symbol_slots": symbol_slots,
        "introduced_at": introduced_at,
    }


def symbol_inventory_burden(
    stats: dict[str, Any],
    recent_stats: dict[str, Any],
) -> dict[str, Any]:
    if not stats["symbol_slots"]:
        return unknown_burden("No symbol-level recognition slots available.")

    rows = symbol_rows_from_stats(stats, recent_stats)
    weakest = min(rows, key=lambda row: (row["lifetime_fraction"], row["lifetime_exposures"]))
    min_exposures = min(row["lifetime_exposures"] for row in rows)
    confidence = _confidence_from_count(
        min_exposures,
        medium=MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE,
        high=MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE,
    )
    debt = debt_from_fraction(weakest["lifetime_fraction"])
    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": symbol_inventory_evidence(rows, context=""),
        "symbols": rows,
    }


def koch_symbol_inventory_burden(
    stats: dict[str, Any],
    *,
    lifetime_stats: dict[str, Any],
    symbol_stats: dict[str, Any],
    recent_symbol_stats: dict[str, Any],
) -> dict[str, Any]:
    total = int(stats["symbol_available"])
    if total <= 0:
        return unknown_burden("No Koch symbol-copy evidence in the recent window.")

    correct = int(stats["symbol_correct"])
    fraction = _fraction(correct, total)
    symbol_rows = symbol_rows_from_stats(
        symbol_stats,
        recent_symbol_stats,
        sort_key=_symbol_sort_key,
    )
    lifetime_total = int(lifetime_stats["symbol_available"])
    lifetime_correct = int(lifetime_stats["symbol_correct"])
    lifetime_fraction = _fraction(lifetime_correct, lifetime_total)
    evidence = [
        f"Recent Koch sessions: copied symbols were correct {_percent(fraction)} of the time.",
        (
            f"Based on {total} copied symbols across "
            f"{_count_label(int(stats['exercise_count']), 'recent exercise')}."
        ),
    ]
    if lifetime_total > 0:
        evidence.extend(
            [
                (
                    "Since this symbol set began: copied symbols are correct "
                    f"{_percent(lifetime_fraction)} of the time."
                ),
                (
                    f"Based on {lifetime_total} copied symbols across "
                    f"{_count_label(int(lifetime_stats['exercise_count']), 'saved exercise')}."
                ),
            ]
        )
    evidence.extend(symbol_inventory_evidence(symbol_rows, context="Koch"))
    return {
        "debt": debt_from_fraction(fraction),
        "confidence": _confidence_from_count(
            total,
            medium=MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE,
            high=MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE,
        ),
        "evidence": evidence,
        "symbol_correct_units": correct,
        "symbol_available_units": total,
        "fraction": round(fraction, 6),
        "lifetime_symbol_correct_units": lifetime_correct,
        "lifetime_symbol_available_units": lifetime_total,
        "lifetime_fraction": round(lifetime_fraction, 6),
        "symbols": symbol_rows,
    }


def symbol_rows_from_stats(
    stats: dict[str, Any],
    recent_stats: dict[str, Any],
    *,
    sort_key: Any = None,
) -> list[dict[str, Any]]:
    symbol_slots: dict[str, Counter[str]] = stats["symbol_slots"]
    recent_symbol_slots: dict[str, Counter[str]] = recent_stats["symbol_slots"]
    introduced_at: dict[str, str] = stats["introduced_at"]
    rows = []
    for symbol in sorted(symbol_slots, key=sort_key):
        counts = symbol_slots[symbol]
        total = sum(counts.values())
        correct = counts["correct"] + counts["caught_correct"]
        recent_counts = recent_symbol_slots.get(symbol, Counter())
        recent_total = sum(recent_counts.values())
        recent_correct = recent_counts["correct"] + recent_counts["caught_correct"]
        rows.append(
            {
                "symbol": symbol,
                "introduced_at": introduced_at.get(symbol, ""),
                "exposures": total,
                "correct": correct,
                "fraction": _fraction(correct, total),
                "misses": counts["miss"],
                "substitutions": counts["substitution"] + counts["caught_substitution"],
                "lifetime_exposures": total,
                "lifetime_correct": correct,
                "lifetime_fraction": _fraction(correct, total),
                "lifetime_misses": counts["miss"],
                "lifetime_substitutions": counts["substitution"] + counts["caught_substitution"],
                "recent_exposures": recent_total,
                "recent_correct": recent_correct,
                "recent_fraction": _fraction(recent_correct, recent_total),
                "recent_misses": recent_counts["miss"],
                "recent_substitutions": recent_counts["substitution"]
                + recent_counts["caught_substitution"],
            }
        )

    for row in rows:
        row["signal"] = _symbol_signal(row)
    return rows


def symbol_inventory_evidence(rows: list[dict[str, Any]], *, context: str) -> list[str]:
    if not rows:
        return []

    evidence = []
    prefix = f"{context} " if context else ""
    weakest = min(rows, key=lambda row: (row["lifetime_fraction"], row["lifetime_exposures"]))
    evidence.append(
        (
            f"Weakest lifetime {prefix}symbol {weakest['symbol']} at "
            f"{_percent(weakest['lifetime_fraction'])} over "
            f"{weakest['lifetime_exposures']} exposures since introduction."
        )
    )
    weakest_recent = min(
        [row for row in rows if row["recent_exposures"] > 0],
        key=lambda row: (row["recent_fraction"], row["recent_exposures"]),
        default=None,
    )
    if weakest_recent:
        evidence.append(
            f"Weakest recent {prefix}symbol {weakest_recent['symbol']} at "
            f"{_percent(weakest_recent['recent_fraction'])} over "
            f"{weakest_recent['recent_exposures']} exposures in the recent window."
        )
    stable = [row["symbol"] for row in rows if row["lifetime_fraction"] >= STRONG_FRACTION]
    if stable:
        evidence.append(
            f"Stable lifetime {prefix}symbols at current evidence threshold: "
            f"{' '.join(stable)}."
        )
    return evidence


def recognition_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if isinstance(record, dict) and record.get("mode") == "recognition"
    ]


def matching_recognition_records(
    records: list[dict[str, Any]],
    claimed_set_key: str,
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("mode") == "recognition"
        and record_claimed_set_key(record) == claimed_set_key
    ]


def debt_from_fraction(value: float) -> str:
    if value >= STRONG_FRACTION:
        return DEBT_LOW
    if value >= LOW_FRACTION:
        return DEBT_MODERATE
    return DEBT_HIGH


def unknown_burden(evidence: str) -> dict[str, Any]:
    return {
        "debt": DEBT_UNKNOWN,
        "confidence": CONFIDENCE_LOW,
        "evidence": [evidence],
    }


def _symbol_sort_key(symbol: str) -> tuple[int, str]:
    try:
        return (patterns.KOCH_ORDER.index(symbol), symbol)
    except ValueError:
        return (len(patterns.KOCH_ORDER), symbol)


def _symbol_signal(row: dict[str, Any]) -> str:
    lifetime_exposures = int(row["lifetime_exposures"])
    recent_exposures = int(row["recent_exposures"])
    lifetime_fraction = float(row["lifetime_fraction"])
    recent_fraction = float(row["recent_fraction"])

    if lifetime_exposures < MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE:
        return "undersampled"
    if recent_exposures < MIN_SYMBOL_RECENT_EXPOSURES_SIGNAL:
        return "watch"
    if lifetime_fraction >= STRONG_FRACTION and recent_fraction >= STRONG_FRACTION:
        return "stable"
    if lifetime_fraction < STRONG_FRACTION and recent_fraction >= STRONG_FRACTION:
        return "recovering"
    if lifetime_fraction < STRONG_FRACTION and recent_fraction < LOW_FRACTION:
        return "fragile"
    return "watch"


def _confidence_from_count(count: int, *, medium: int, high: int) -> str:
    if count >= high:
        return CONFIDENCE_HIGH
    if count >= medium:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _fraction(correct: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, correct / total))


def _percent(value: float) -> str:
    return f"{round(value * 100, 1)}%"


def _count_label(count: int, singular: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {singular}{suffix}"
