"""Burden-debt profile derivation for saved recognition evidence.

This module is read-only analysis. It interprets existing Symbol
Recognition records into backend evidence about burdens, debt, and
confidence; it does not change generation or learner-facing progression.
"""

from __future__ import annotations

from collections import Counter
from collections import defaultdict
from typing import Any

from copy_653.sequence.exercise_analysis import LOW_FRACTION, STRONG_FRACTION
from copy_653.sequence.exercise_analysis import DEFAULT_EVIDENCE_WINDOW_SIZE
from copy_653.sequence.exercise_analysis import record_claimed_set_key

BURDEN_PROFILE_VERSION = "burden-profile-v1"

DEBT_LOW = "low"
DEBT_MODERATE = "moderate"
DEBT_HIGH = "high"
DEBT_UNKNOWN = "unknown"

CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE = 8
MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE = 20
MIN_UNIT_EXERCISES_MEDIUM_CONFIDENCE = 4
MIN_UNIT_EXERCISES_HIGH_CONFIDENCE = 10
MIN_CONFUSION_EXPOSURES_MEDIUM_CONFIDENCE = 20
MIN_CONFUSION_EXPOSURES_HIGH_CONFIDENCE = 80

MODERATE_CONFUSION_COUNT = 2
HIGH_CONFUSION_COUNT = 4


def load_recognition_burden_profile(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_EVIDENCE_WINDOW_SIZE,
) -> dict[str, Any]:
    """Build a read-only burden debt profile from recognition records.

    The initial implementation intentionally uses only burden axes for
    which current recognition records already carry meaningful evidence:

    * symbol inventory
    * unit length
    * confusion pressure

    Signal, rhythm, anchor, and practice-transfer debt remain unknown
    until first-class probes or comparable condition evidence exist.
    """
    matching = _matching_recognition_records(records, claimed_set_key)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    recent = matching[: max(0, window_size)]
    stats = _collect_stats(recent)

    return {
        "version": BURDEN_PROFILE_VERSION,
        "claimed_set_key": claimed_set_key,
        "record_count": len(matching),
        "window_size": max(0, window_size),
        "records_used": len(recent),
        "burdens": {
            "symbol_inventory": _symbol_inventory_burden(stats),
            "unit_length": _unit_length_burden(stats),
            "confusion": _confusion_burden(stats),
            "signal": _unknown_burden("No signal probes or receiver-bed contrast evidence yet."),
            "rhythm": _unknown_burden("No cadence-variation probes or contrast evidence yet."),
            "anchor": _unknown_burden("No anchor-removal probes or contrast evidence yet."),
            "practice_transfer": _unknown_burden(
                "No linked Symbol Recognition to Koch Exercise transfer evidence yet."
            ),
        },
    }


def _matching_recognition_records(
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


def _collect_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    symbol_slots: dict[str, Counter[str]] = defaultdict(Counter)
    unit_attempts: dict[int, list[float]] = defaultdict(list)
    committed_confusions: Counter[tuple[str, str]] = Counter()
    caught_confusions: Counter[tuple[str, str]] = Counter()

    for record in records:
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("has_evidence") is not True:
                continue

            gear = _coerce_int(exercise.get("gear"), _record_gear(record))
            fraction = analysis.get("combined_fraction")
            if isinstance(fraction, (int, float)) and not isinstance(fraction, bool):
                unit_attempts[gear].append(float(fraction))

            slots = analysis.get("slots")
            if isinstance(slots, list):
                for slot in slots:
                    if not isinstance(slot, dict):
                        continue
                    truth = slot.get("truth")
                    outcome = slot.get("outcome")
                    if isinstance(truth, str) and truth and isinstance(outcome, str):
                        symbol_slots[truth.upper()][outcome] += 1

            for pair in analysis.get("committed_confusions") or []:
                _tally_pair(committed_confusions, pair)

            timing = exercise.get("timing_analysis")
            if isinstance(timing, dict):
                for pair in timing.get("caught_confusions") or []:
                    _tally_pair(caught_confusions, pair)

    return {
        "symbol_slots": symbol_slots,
        "unit_attempts": unit_attempts,
        "committed_confusions": committed_confusions,
        "caught_confusions": caught_confusions,
    }


def _symbol_inventory_burden(stats: dict[str, Any]) -> dict[str, Any]:
    symbol_slots: dict[str, Counter[str]] = stats["symbol_slots"]
    if not symbol_slots:
        return _unknown_burden("No symbol-level recognition slots available.")

    rows = []
    for symbol in sorted(symbol_slots):
        counts = symbol_slots[symbol]
        total = sum(counts.values())
        correct = counts["correct"] + counts["caught_correct"]
        rows.append(
            {
                "symbol": symbol,
                "exposures": total,
                "correct": correct,
                "fraction": _fraction(correct, total),
                "misses": counts["miss"],
                "substitutions": counts["substitution"] + counts["caught_substitution"],
            }
        )

    weakest = min(rows, key=lambda row: (row["fraction"], row["exposures"]))
    min_exposures = min(row["exposures"] for row in rows)
    confidence = _confidence_from_count(
        min_exposures,
        medium=MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE,
        high=MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE,
    )
    debt = _debt_from_fraction(weakest["fraction"])
    evidence = [
        (
            f"Weakest symbol {weakest['symbol']} at "
            f"{_percent(weakest['fraction'])} over {weakest['exposures']} exposures."
        )
    ]
    stable = [row["symbol"] for row in rows if row["fraction"] >= STRONG_FRACTION]
    if stable:
        evidence.append(f"Stable symbols at current evidence threshold: {' '.join(stable)}.")

    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": evidence,
        "symbols": rows,
    }


def _unit_length_burden(stats: dict[str, Any]) -> dict[str, Any]:
    unit_attempts: dict[int, list[float]] = stats["unit_attempts"]
    grouped = [
        fraction for gear, fractions in unit_attempts.items() if gear >= 1 for fraction in fractions
    ]
    if not grouped:
        return _unknown_burden("No pair or longer-unit recognition evidence yet.")

    average = sum(grouped) / len(grouped)
    debt = _debt_from_fraction(average)
    confidence = _confidence_from_count(
        len(grouped),
        medium=MIN_UNIT_EXERCISES_MEDIUM_CONFIDENCE,
        high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
    )
    evidence = [
        f"Grouped-unit recognition averaged {_percent(average)} " f"over {len(grouped)} exercises."
    ]
    singles = unit_attempts.get(0, [])
    if singles:
        single_average = sum(singles) / len(singles)
        evidence.append(
            f"Single-symbol recognition averaged {_percent(single_average)} "
            f"over {len(singles)} exercises."
        )

    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": evidence,
        "exercise_count": len(grouped),
        "average_fraction": round(average, 6),
    }


def _confusion_burden(stats: dict[str, Any]) -> dict[str, Any]:
    committed: Counter[tuple[str, str]] = stats["committed_confusions"]
    caught: Counter[tuple[str, str]] = stats["caught_confusions"]
    symbol_slots: dict[str, Counter[str]] = stats["symbol_slots"]
    exposures = sum(sum(counts.values()) for counts in symbol_slots.values())

    if exposures <= 0:
        return _unknown_burden("No recognition slots available for confusion evidence.")

    confidence = _confidence_from_count(
        exposures,
        medium=MIN_CONFUSION_EXPOSURES_MEDIUM_CONFIDENCE,
        high=MIN_CONFUSION_EXPOSURES_HIGH_CONFIDENCE,
    )
    if not committed:
        return {
            "debt": DEBT_LOW,
            "confidence": confidence,
            "evidence": [f"No committed confusions across {exposures} symbol exposures."],
            "committed": [],
            "caught": _format_pairs(caught),
        }

    top_pair, top_count = committed.most_common(1)[0]
    if top_count >= HIGH_CONFUSION_COUNT:
        debt = DEBT_HIGH
    elif top_count >= MODERATE_CONFUSION_COUNT:
        debt = DEBT_MODERATE
    else:
        debt = DEBT_LOW

    evidence = [
        f"Top committed confusion {top_pair[0]} -> {top_pair[1]} " f"occurred {top_count} times."
    ]
    if caught:
        caught_pair, caught_count = caught.most_common(1)[0]
        evidence.append(
            f"Top caught confusion {caught_pair[0]} -> {caught_pair[1]} "
            f"occurred {caught_count} times."
        )

    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": evidence,
        "committed": _format_pairs(committed),
        "caught": _format_pairs(caught),
    }


def _unknown_burden(evidence: str) -> dict[str, Any]:
    return {
        "debt": DEBT_UNKNOWN,
        "confidence": CONFIDENCE_LOW,
        "evidence": [evidence],
    }


def _debt_from_fraction(value: float) -> str:
    if value >= STRONG_FRACTION:
        return DEBT_LOW
    if value >= LOW_FRACTION:
        return DEBT_MODERATE
    return DEBT_HIGH


def _confidence_from_count(count: int, *, medium: int, high: int) -> str:
    if count >= high:
        return CONFIDENCE_HIGH
    if count >= medium:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _tally_pair(counter: Counter[tuple[str, str]], pair: Any) -> None:
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return
    target, typed = pair
    if isinstance(target, str) and isinstance(typed, str):
        counter[(target.upper(), typed.upper())] += 1


def _format_pairs(counter: Counter[tuple[str, str]]) -> list[dict[str, Any]]:
    return [
        {"target": target, "typed": typed, "count": count}
        for (target, typed), count in counter.most_common()
    ]


def _record_gear(record: dict[str, Any]) -> int:
    generation = record.get("generation")
    if not isinstance(generation, dict):
        return 0
    return _coerce_int(generation.get("gear"), 0)


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
