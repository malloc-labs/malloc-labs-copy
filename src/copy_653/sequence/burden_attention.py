"""Attention response analysis for saved Recognition and Koch evidence."""

from __future__ import annotations

from typing import Any

from copy_653.sequence.exercise_analysis import (
    DEFAULT_EVIDENCE_WINDOW_SIZE as DEFAULT_KOCH_BURDEN_WINDOW_SIZE,
    record_claimed_set_key,
)

ATTENTION_RESPONSE_VERSION = "attention-response-v1"
DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE = 20

ATTENTION_MIN_EXERCISES_PER_CONDITION = 4
ATTENTION_HELPED_DELTA = 0.05
ATTENTION_NEUTRAL_DELTA = 0.02
MIN_UNIT_EXERCISES_HIGH_CONFIDENCE = 10

CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"


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


def koch_attention_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
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


def recognition_attention_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
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
    metrics = koch_attention_metrics(rows)
    reference = koch_attention_metrics(reference_rows)
    confidence = _confidence_from_count(
        len(rows),
        medium=ATTENTION_MIN_EXERCISES_PER_CONDITION,
        high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
    )
    axes = {
        "symbols": _attention_axis(
            metrics,
            reference,
            "symbol_fraction",
            "exercise_count",
        ),
        "grouping": _attention_axis(
            metrics,
            reference,
            "grouping_fraction",
            "spacing_available_units",
        ),
        "unit_length": _attention_axis(
            metrics,
            reference,
            "unit_length_fraction",
            "unit_length_exercise_count",
        ),
        "overall": _attention_axis(
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
    metrics = recognition_attention_metrics(rows)
    reference = recognition_attention_metrics(reference_rows)
    confidence = _confidence_from_count(
        len(rows),
        medium=ATTENTION_MIN_EXERCISES_PER_CONDITION,
        high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
    )
    axes = {
        "accuracy": _attention_axis(
            metrics,
            reference,
            "accuracy_fraction",
            "exercise_count",
        ),
        "misses": _attention_axis(
            metrics,
            reference,
            "miss_avoidance_fraction",
            "slot_count",
        ),
        "confusions": _attention_axis(
            metrics,
            reference,
            "confusion_avoidance_fraction",
            "slot_count",
        ),
        "overall": _attention_axis(
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


def _attention_axis(
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


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)
