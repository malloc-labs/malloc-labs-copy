"""Burden-debt profile derivation for saved recognition evidence.

This module is read-only analysis. It interprets existing Symbol
Recognition records into backend evidence about burdens, debt, and
confidence; it does not change generation or learner-facing progression.
"""

from __future__ import annotations

from collections import Counter
from collections import defaultdict
from typing import Any

from copy_653.sequence.exercise_analysis import (
    DEFAULT_EVIDENCE_WINDOW_SIZE as DEFAULT_KOCH_BURDEN_WINDOW_SIZE,
    LOW_FRACTION,
    STRONG_FRACTION,
    load_confusion_pairs,
    record_claimed_set_key,
)

BURDEN_PROFILE_VERSION = "burden-profile-v1"
ATTENTION_RESPONSE_VERSION = "attention-response-v1"
DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE = 20

DEBT_LOW = "low"
DEBT_MODERATE = "moderate"
DEBT_HIGH = "high"
DEBT_UNKNOWN = "unknown"

CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE = 8
MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE = 20
MIN_SYMBOL_RECENT_EXPOSURES_SIGNAL = 8
MIN_UNIT_EXERCISES_MEDIUM_CONFIDENCE = 4
MIN_UNIT_EXERCISES_HIGH_CONFIDENCE = 10
MIN_CONFUSION_EXPOSURES_MEDIUM_CONFIDENCE = 20
MIN_CONFUSION_EXPOSURES_HIGH_CONFIDENCE = 80

MODERATE_CONFUSION_COUNT = 2
HIGH_CONFUSION_COUNT = 4

ATTENTION_MIN_EXERCISES_PER_CONDITION = 4
ATTENTION_HELPED_DELTA = 0.05
ATTENTION_NEUTRAL_DELTA = 0.02


def load_recognition_burden_profile(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE,
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
    claimed_symbols = set(claimed_set_key.split())
    stats = _collect_stats(recent)
    symbol_stats = _collect_symbol_stats(records, symbols=claimed_symbols)
    recent_symbol_stats = _collect_symbol_stats(recent, symbols=claimed_symbols)

    return {
        "version": BURDEN_PROFILE_VERSION,
        "claimed_set_key": claimed_set_key,
        "record_count": len(matching),
        "window_size": max(0, window_size),
        "records_used": len(recent),
        "burdens": {
            "symbol_inventory": _symbol_inventory_burden(symbol_stats, recent_symbol_stats),
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


def load_koch_burden_profile(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_KOCH_BURDEN_WINDOW_SIZE,
) -> dict[str, Any]:
    """Build a burden-axis profile from saved Koch Exercise evidence.

    Koch generation still runs on bands and gears, but the settings
    burden table should describe the listening burdens those mechanisms
    probe. Band and gear remain provenance inside the evidence strings.
    """
    matching = _matching_koch_records(records, claimed_set_key)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    recent = matching[: max(0, window_size)]
    stats = _collect_koch_stats(recent)
    confusions = load_confusion_pairs(records, claimed_set_key=claimed_set_key)

    return {
        "version": BURDEN_PROFILE_VERSION,
        "claimed_set_key": claimed_set_key,
        "record_count": len(matching),
        "window_size": max(0, window_size),
        "records_used": len(recent),
        "burdens": {
            "symbol_inventory": _koch_symbol_inventory_burden(stats),
            "grouping": _koch_grouping_burden(stats),
            "unit_length": _koch_unit_length_burden(stats),
            "confusion": _koch_confusion_burden(confusions),
            "signal": _unknown_burden("No Koch receiver-bed contrast probes yet."),
            "rhythm": _unknown_burden("No Koch cadence-variation contrast probes yet."),
            "anchor": _unknown_burden("No Koch anchor-removal contrast probes yet."),
            "practice_transfer": _unknown_burden(
                "No linked Symbol Recognition to Koch Exercise transfer evidence yet."
            ),
        },
    }


def load_koch_attention_response(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_KOCH_BURDEN_WINDOW_SIZE,
) -> dict[str, Any]:
    """Compare Koch copy stability across saved per-exercise S/T conditions.

    This is deliberately separate from burden debt: the response may be
    helpful, neutral, or harmful, and lower S is not assumed to be worse.
    """
    matching = _matching_koch_records(records, claimed_set_key)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    recent = matching[: max(0, window_size)]
    exercises = _collect_koch_attention_exercises(recent)
    lower = [row for row in exercises if 2 <= row["s"] <= 6]
    higher = [row for row in exercises if 7 <= row["s"] <= 9]

    return {
        "version": ATTENTION_RESPONSE_VERSION,
        "claimed_set_key": claimed_set_key,
        "record_count": len(matching),
        "window_size": max(0, window_size),
        "records_used": len(recent),
        "exercise_count": len(exercises),
        "conditions": [
            _koch_attention_condition(
                key="lower_s",
                label="Lower S / more texture",
                rows=lower,
                reference_rows=higher,
            ),
            _koch_attention_condition(
                key="higher_s",
                label="Higher S / cleaner signal",
                rows=higher,
                reference_rows=lower,
            ),
        ],
    }


def load_recognition_attention_response(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE,
) -> dict[str, Any]:
    """Compare recognition stability across saved per-exercise S/T conditions."""
    matching = _matching_recognition_records(records, claimed_set_key)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    recent = matching[: max(0, window_size)]
    exercises = _collect_recognition_attention_exercises(recent)
    lower = [row for row in exercises if 2 <= row["s"] <= 6]
    higher = [row for row in exercises if 7 <= row["s"] <= 9]

    return {
        "version": ATTENTION_RESPONSE_VERSION,
        "claimed_set_key": claimed_set_key,
        "record_count": len(matching),
        "window_size": max(0, window_size),
        "records_used": len(recent),
        "exercise_count": len(exercises),
        "conditions": [
            _recognition_attention_condition(
                key="lower_s",
                label="Lower S / more texture",
                rows=lower,
                reference_rows=higher,
            ),
            _recognition_attention_condition(
                key="higher_s",
                label="Higher S / cleaner signal",
                rows=higher,
                reference_rows=lower,
            ),
        ],
    }


def _recognition_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if isinstance(record, dict) and record.get("mode") == "recognition"
    ]


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


def _matching_koch_records(
    records: list[dict[str, Any]],
    claimed_set_key: str,
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("mode") == "koch-exercise"
        and record.get("warm_up") is not True
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


def _collect_koch_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    symbol_correct = 0
    symbol_available = 0
    spacing_correct = 0
    spacing_available = 0
    band_attempts: dict[int, list[tuple[float, int]]] = defaultdict(list)
    exercise_count = 0

    for record in records:
        session_gears = _koch_gears_from_generation(record.get("generation"))
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("saved") is not True:
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue

            symbol_correct += _coerce_int(analysis.get("symbol_correct_units"), 0)
            symbol_available += _coerce_int(analysis.get("symbol_available_units"), 0)
            spacing_correct += _coerce_int(analysis.get("spacing_correct_units"), 0)
            spacing_available += _coerce_int(analysis.get("spacing_available_units"), 0)

            band = _coerce_int(exercise.get("burden_band"), 0)
            gear = session_gears.get(band, _coerce_int(exercise.get("gear"), 0))
            if band > 0:
                band_attempts[band].append((float(fraction), gear))
            exercise_count += 1

    return {
        "symbol_correct": symbol_correct,
        "symbol_available": symbol_available,
        "spacing_correct": spacing_correct,
        "spacing_available": spacing_available,
        "band_attempts": band_attempts,
        "exercise_count": exercise_count,
    }


def _collect_koch_attention_exercises(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            s = _coerce_int(exercise.get("s"), 0)
            t = _coerce_int(exercise.get("t"), 0)
            if not (2 <= s <= 9 and 1 <= t <= 9):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("saved") is not True:
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            rows.append(
                {
                    "s": s,
                    "t": t,
                    "combined_fraction": float(fraction),
                    "symbol_correct": _coerce_int(analysis.get("symbol_correct_units"), 0),
                    "symbol_available": _coerce_int(analysis.get("symbol_available_units"), 0),
                    "spacing_correct": _coerce_int(analysis.get("spacing_correct_units"), 0),
                    "spacing_available": _coerce_int(analysis.get("spacing_available_units"), 0),
                    "burden_band": _coerce_int(exercise.get("burden_band"), 0),
                }
            )
    return rows


def _collect_recognition_attention_exercises(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            s = _coerce_int(exercise.get("s"), 0)
            t = _coerce_int(exercise.get("t"), 0)
            if not (2 <= s <= 9 and 1 <= t <= 9):
                continue
            analysis = exercise.get("analysis")
            if (
                not isinstance(analysis, dict)
                or analysis.get("saved") is not True
                or analysis.get("has_evidence") is not True
            ):
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            counts = analysis.get("counts")
            if not isinstance(counts, dict):
                counts = {}
            rows.append(
                {
                    "s": s,
                    "t": t,
                    "combined_fraction": float(fraction),
                    "correct": _coerce_int(counts.get("correct"), 0)
                    + _coerce_int(counts.get("caught_correct"), 0),
                    "substitutions": _coerce_int(counts.get("substitution"), 0)
                    + _coerce_int(counts.get("caught_substitution"), 0),
                    "misses": _coerce_int(counts.get("miss"), 0),
                    "slot_count": sum(_coerce_int(value, 0) for value in counts.values()),
                }
            )
    return rows


def _koch_attention_condition(
    *,
    key: str,
    label: str,
    rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = _koch_attention_metrics(rows)
    reference = _koch_attention_metrics(reference_rows)
    confidence = _confidence_from_count(
        len(rows),
        medium=ATTENTION_MIN_EXERCISES_PER_CONDITION,
        high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
    )
    axes = {
        "symbols": _koch_attention_axis(
            metrics,
            reference,
            "symbol_fraction",
            "exercise_count",
        ),
        "grouping": _koch_attention_axis(
            metrics,
            reference,
            "grouping_fraction",
            "spacing_available_units",
        ),
        "unit_length": _koch_attention_axis(
            metrics,
            reference,
            "unit_length_fraction",
            "unit_length_exercise_count",
        ),
        "overall": _koch_attention_axis(
            metrics,
            reference,
            "overall_fraction",
            "exercise_count",
        ),
    }
    st_range = _format_st_range(rows)
    return {
        "key": key,
        "label": label,
        "st_range": st_range,
        "confidence": confidence,
        "exercise_count": len(rows),
        "reference_count": len(reference_rows),
        "axes": axes,
        "metrics": metrics,
        "reference_metrics": reference,
        "evidence": [
            _koch_attention_evidence(label, st_range, metrics, rows, reference_rows),
        ],
    }


def _recognition_attention_condition(
    *,
    key: str,
    label: str,
    rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = _recognition_attention_metrics(rows)
    reference = _recognition_attention_metrics(reference_rows)
    confidence = _confidence_from_count(
        len(rows),
        medium=ATTENTION_MIN_EXERCISES_PER_CONDITION,
        high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
    )
    axes = {
        "accuracy": _koch_attention_axis(
            metrics,
            reference,
            "accuracy_fraction",
            "exercise_count",
        ),
        "misses": _koch_attention_axis(
            metrics,
            reference,
            "miss_avoidance_fraction",
            "slot_count",
        ),
        "confusions": _koch_attention_axis(
            metrics,
            reference,
            "confusion_avoidance_fraction",
            "slot_count",
        ),
        "overall": _koch_attention_axis(
            metrics,
            reference,
            "overall_fraction",
            "exercise_count",
        ),
    }
    st_range = _format_st_range(rows)
    return {
        "key": key,
        "label": label,
        "st_range": st_range,
        "confidence": confidence,
        "exercise_count": len(rows),
        "reference_count": len(reference_rows),
        "axes": axes,
        "metrics": metrics,
        "reference_metrics": reference,
        "evidence": [
            _recognition_attention_evidence(label, st_range, metrics, rows, reference_rows),
        ],
    }


def _koch_attention_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    symbol_correct = sum(int(row["symbol_correct"]) for row in rows)
    symbol_available = sum(int(row["symbol_available"]) for row in rows)
    spacing_correct = sum(int(row["spacing_correct"]) for row in rows)
    spacing_available = sum(int(row["spacing_available"]) for row in rows)
    fractions = [float(row["combined_fraction"]) for row in rows]
    unit_length_fractions = [
        float(row["combined_fraction"]) for row in rows if int(row["burden_band"]) >= 3
    ]
    return {
        "exercise_count": len(rows),
        "symbol_fraction": (
            _round_or_none(_fraction(symbol_correct, symbol_available))
            if symbol_available
            else None
        ),
        "grouping_fraction": (
            _round_or_none(_fraction(spacing_correct, spacing_available))
            if spacing_available
            else None
        ),
        "unit_length_fraction": (
            _round_or_none(sum(unit_length_fractions) / len(unit_length_fractions))
            if unit_length_fractions
            else None
        ),
        "unit_length_exercise_count": len(unit_length_fractions),
        "overall_fraction": _round_or_none(sum(fractions) / len(fractions)) if fractions else None,
        "symbol_correct_units": symbol_correct,
        "symbol_available_units": symbol_available,
        "spacing_correct_units": spacing_correct,
        "spacing_available_units": spacing_available,
        "perfect_exercises": sum(1 for row in rows if float(row["combined_fraction"]) == 1.0),
    }


def _recognition_attention_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    slot_count = sum(int(row["slot_count"]) for row in rows)
    correct = sum(int(row["correct"]) for row in rows)
    substitutions = sum(int(row["substitutions"]) for row in rows)
    misses = sum(int(row["misses"]) for row in rows)
    fractions = [float(row["combined_fraction"]) for row in rows]
    return {
        "exercise_count": len(rows),
        "slot_count": slot_count,
        "accuracy_fraction": _round_or_none(_fraction(correct, slot_count)) if slot_count else None,
        "miss_avoidance_fraction": (
            _round_or_none(_fraction(slot_count - misses, slot_count)) if slot_count else None
        ),
        "confusion_avoidance_fraction": (
            _round_or_none(_fraction(slot_count - substitutions, slot_count))
            if slot_count
            else None
        ),
        "overall_fraction": _round_or_none(sum(fractions) / len(fractions)) if fractions else None,
        "correct_units": correct,
        "substitution_units": substitutions,
        "miss_units": misses,
    }


def _koch_attention_axis(
    metrics: dict[str, Any],
    reference: dict[str, Any],
    metric_key: str,
    count_key: str,
) -> dict[str, Any]:
    value = metrics.get(metric_key)
    reference_value = reference.get(metric_key)
    count = _coerce_int(metrics.get(count_key), 0)
    reference_count = _coerce_int(reference.get(count_key), 0)
    if (
        value is None
        or reference_value is None
        or count < ATTENTION_MIN_EXERCISES_PER_CONDITION
        or reference_count < ATTENTION_MIN_EXERCISES_PER_CONDITION
    ):
        return {
            "response": "unknown",
            "value": value,
            "reference": reference_value,
            "delta": None,
        }

    delta = float(value) - float(reference_value)
    if delta >= ATTENTION_HELPED_DELTA:
        response = "helped"
    elif delta <= -ATTENTION_HELPED_DELTA:
        response = "hurt"
    elif abs(delta) <= ATTENTION_NEUTRAL_DELTA:
        response = "neutral"
    else:
        response = "mixed"
    return {
        "response": response,
        "value": value,
        "reference": reference_value,
        "delta": round(delta, 6),
    }


def _format_st_range(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "not observed"
    s_values = [int(row["s"]) for row in rows]
    t_values = [int(row["t"]) for row in rows]
    return f"{_format_prefixed_range('S', s_values)} / {_format_prefixed_range('T', t_values)}"


def _format_prefixed_range(prefix: str, values: list[int]) -> str:
    if not values:
        return f"{prefix}?"
    low = min(values)
    high = max(values)
    if low == high:
        return f"{prefix}{low}"
    return f"{prefix}{low}-{prefix}{high}"


def _koch_attention_evidence(
    label: str,
    st_range: str,
    metrics: dict[str, Any],
    rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
) -> str:
    if not rows:
        return f"{label}: no saved Koch exercises with per-exercise S/T evidence."
    overall = metrics.get("overall_fraction")
    percent = _percent(float(overall)) if isinstance(overall, (int, float)) else "unknown"
    return (
        f"{label} ({st_range}) averaged {percent} over {len(rows)} exercises, "
        f"compared with {len(reference_rows)} exercises in the opposite S condition."
    )


def _recognition_attention_evidence(
    label: str,
    st_range: str,
    metrics: dict[str, Any],
    rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
) -> str:
    if not rows:
        return f"{label}: no saved recognition exercises with per-exercise S/T evidence."
    overall = metrics.get("overall_fraction")
    percent = _percent(float(overall)) if isinstance(overall, (int, float)) else "unknown"
    return (
        f"{label} ({st_range}) averaged {percent} over {len(rows)} exercises, "
        f"compared with {len(reference_rows)} exercises in the opposite S condition."
    )


def _koch_symbol_inventory_burden(stats: dict[str, Any]) -> dict[str, Any]:
    total = int(stats["symbol_available"])
    if total <= 0:
        return _unknown_burden("No Koch symbol-copy evidence in the recent window.")

    correct = int(stats["symbol_correct"])
    fraction = _fraction(correct, total)
    return {
        "debt": _debt_from_fraction(fraction),
        "confidence": _confidence_from_count(
            total,
            medium=MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE,
            high=MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE,
        ),
        "evidence": [
            f"Koch symbol stream copied at {_percent(fraction)} "
            f"over {total} symbol units in the recent window."
        ],
        "symbol_correct_units": correct,
        "symbol_available_units": total,
        "fraction": round(fraction, 6),
    }


def _koch_grouping_burden(stats: dict[str, Any]) -> dict[str, Any]:
    total = int(stats["spacing_available"])
    if total <= 0:
        return _unknown_burden("No Koch word-boundary evidence in the recent window.")

    correct = int(stats["spacing_correct"])
    fraction = _fraction(correct, total)
    return {
        "debt": _debt_from_fraction(fraction),
        "confidence": _confidence_from_count(
            total,
            medium=MIN_UNIT_EXERCISES_MEDIUM_CONFIDENCE,
            high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
        ),
        "evidence": [
            f"Koch grouping copied at {_percent(fraction)} "
            f"over {total} word-boundary units in the recent window."
        ],
        "spacing_correct_units": correct,
        "spacing_available_units": total,
        "fraction": round(fraction, 6),
    }


def _koch_unit_length_burden(stats: dict[str, Any]) -> dict[str, Any]:
    band_attempts: dict[int, list[tuple[float, int]]] = stats["band_attempts"]
    if not band_attempts:
        return _unknown_burden("No Koch band evidence in the recent window.")

    rows = []
    for band, entries in sorted(band_attempts.items()):
        fractions = [fraction for fraction, _gear in entries]
        average = sum(fractions) / len(fractions)
        rows.append(
            {
                "band": band,
                "average_fraction": average,
                "exercise_count": len(entries),
                "current_gear": entries[0][1],
            }
        )
    weakest = min(rows, key=lambda row: (row["average_fraction"], -row["band"]))
    all_fractions = [fraction for entries in band_attempts.values() for fraction, _gear in entries]
    average = sum(all_fractions) / len(all_fractions)

    return {
        "debt": _debt_from_fraction(float(weakest["average_fraction"])),
        "confidence": _confidence_from_count(
            len(all_fractions),
            medium=MIN_UNIT_EXERCISES_MEDIUM_CONFIDENCE,
            high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
        ),
        "evidence": [
            f"Weakest Koch unit-length band {weakest['band']} averaged "
            f"{_percent(float(weakest['average_fraction']))} over "
            f"{weakest['exercise_count']} exercises at gear {weakest['current_gear']}.",
            f"All Koch bands averaged {_percent(average)} over "
            f"{len(all_fractions)} exercises in the recent window.",
        ],
        "bands": [
            {
                **row,
                "average_fraction": round(float(row["average_fraction"]), 6),
            }
            for row in rows
        ],
        "average_fraction": round(average, 6),
    }


def _koch_confusion_burden(confusions: dict[str, Any]) -> dict[str, Any]:
    substitutions = confusions.get("substitutions")
    pairs = substitutions if isinstance(substitutions, list) else []
    exercises_used = _coerce_int(confusions.get("exercises_used"), 0)
    if exercises_used <= 0:
        return _unknown_burden("No saved Koch answers available for confusion evidence.")

    confidence = _confidence_from_count(
        exercises_used,
        medium=MIN_UNIT_EXERCISES_MEDIUM_CONFIDENCE,
        high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
    )
    if not pairs:
        return {
            "debt": DEBT_LOW,
            "confidence": confidence,
            "evidence": [f"No Koch symbol substitutions across {exercises_used} exercises."],
            "committed": [],
        }

    top = pairs[0]
    top_count = _coerce_int(top.get("count") if isinstance(top, dict) else None, 0)
    if top_count >= HIGH_CONFUSION_COUNT:
        debt = DEBT_HIGH
    elif top_count >= MODERATE_CONFUSION_COUNT:
        debt = DEBT_MODERATE
    else:
        debt = DEBT_LOW

    target = top.get("target", "?") if isinstance(top, dict) else "?"
    typed = top.get("typed", "?") if isinstance(top, dict) else "?"
    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": [f"Top Koch symbol confusion {target} -> {typed} occurred {top_count} times."],
        "committed": pairs,
    }


def _collect_symbol_stats(
    records: list[dict[str, Any]],
    *,
    symbols: set[str],
) -> dict[str, Any]:
    symbol_slots: dict[str, Counter[str]] = defaultdict(Counter)
    introduced_at: dict[str, str] = {}

    for record in sorted(
        _recognition_records(records), key=lambda r: str(r.get("started_at") or "")
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


def _symbol_inventory_burden(
    stats: dict[str, Any],
    recent_stats: dict[str, Any],
) -> dict[str, Any]:
    symbol_slots: dict[str, Counter[str]] = stats["symbol_slots"]
    recent_symbol_slots: dict[str, Counter[str]] = recent_stats["symbol_slots"]
    introduced_at: dict[str, str] = stats["introduced_at"]
    if not symbol_slots:
        return _unknown_burden("No symbol-level recognition slots available.")

    rows = []
    for symbol in sorted(symbol_slots):
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

    weakest = min(rows, key=lambda row: (row["lifetime_fraction"], row["lifetime_exposures"]))
    min_exposures = min(row["lifetime_exposures"] for row in rows)
    confidence = _confidence_from_count(
        min_exposures,
        medium=MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE,
        high=MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE,
    )
    debt = _debt_from_fraction(weakest["lifetime_fraction"])
    evidence = [
        (
            f"Weakest lifetime symbol {weakest['symbol']} at "
            f"{_percent(weakest['lifetime_fraction'])} over "
            f"{weakest['lifetime_exposures']} exposures since introduction."
        )
    ]
    weakest_recent = min(
        [row for row in rows if row["recent_exposures"] > 0],
        key=lambda row: (row["recent_fraction"], row["recent_exposures"]),
        default=None,
    )
    if weakest_recent:
        evidence.append(
            f"Weakest recent symbol {weakest_recent['symbol']} at "
            f"{_percent(weakest_recent['recent_fraction'])} over "
            f"{weakest_recent['recent_exposures']} exposures in the recent window."
        )
    stable = [row["symbol"] for row in rows if row["lifetime_fraction"] >= STRONG_FRACTION]
    if stable:
        evidence.append(
            f"Stable lifetime symbols at current evidence threshold: {' '.join(stable)}."
        )

    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": evidence,
        "symbols": rows,
    }


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


def _koch_gears_from_generation(generation: Any) -> dict[int, int]:
    if not isinstance(generation, dict):
        return {}
    bands = generation.get("bands")
    if not isinstance(bands, list):
        return {}
    out: dict[int, int] = {}
    for entry in bands:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        gear = entry.get("gear")
        if (
            isinstance(idx, int)
            and not isinstance(idx, bool)
            and isinstance(gear, int)
            and not isinstance(gear, bool)
        ):
            out[idx] = gear
    return out


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


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)
