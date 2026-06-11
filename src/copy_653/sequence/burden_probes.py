"""Listening-condition and rhythm probe burden analysis."""

from __future__ import annotations

from typing import Any

from copy_653.sequence.burden_attention import (
    ATTENTION_MIN_EXERCISES_PER_CONDITION,
    koch_attention_metrics,
    recognition_attention_metrics,
)
from copy_653.sequence.listening_conditions import (
    KOCH_LISTENING_PROBE_VERSION,
    KOCH_PROBE_PHASE_CHALLENGE,
    LISTENING_CONDITION_DEFAULT,
    LISTENING_CONDITION_TEXTURED,
    RECOGNITION_LISTENING_PROBE_VERSION,
)

DEBT_LOW = "low"
DEBT_MODERATE = "moderate"
DEBT_HIGH = "high"
DEBT_UNKNOWN = "unknown"

CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

LISTENING_MIN_EXERCISES_PER_CONDITION = 2
LISTENING_MODERATE_DELTA = 0.05
LISTENING_HIGH_DELTA = 0.12
RHYTHM_PROBE_VERSION = "recognition-rhythm-v1"
RHYTHM_MIN_EXERCISES_PER_CONDITION = 2
RHYTHM_MODERATE_DELTA = 0.05
RHYTHM_HIGH_DELTA = 0.12
MIN_UNIT_EXERCISES_HIGH_CONFIDENCE = 10


def collect_koch_listening_probe_exercises(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        generation = record.get("generation")
        probe = generation.get("listening_probe") if isinstance(generation, dict) else None
        if not isinstance(probe, dict) or probe.get("version") != KOCH_LISTENING_PROBE_VERSION:
            continue
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            if exercise.get("listening_probe") != KOCH_LISTENING_PROBE_VERSION:
                continue
            condition = exercise.get("listening_condition")
            if condition not in {LISTENING_CONDITION_DEFAULT, LISTENING_CONDITION_TEXTURED}:
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("saved") is not True:
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            rows.append(
                {
                    "condition": condition,
                    "probe_phase": str(exercise.get("probe_phase") or ""),
                    "s": _coerce_int(exercise.get("s"), 0),
                    "t": _coerce_int(exercise.get("t"), 0),
                    "combined_fraction": float(fraction),
                    "symbol_correct": _coerce_int(analysis.get("symbol_correct_units"), 0),
                    "symbol_available": _coerce_int(analysis.get("symbol_available_units"), 0),
                    "spacing_correct": _coerce_int(analysis.get("spacing_correct_units"), 0),
                    "spacing_available": _coerce_int(analysis.get("spacing_available_units"), 0),
                    "burden_band": _coerce_int(exercise.get("burden_band"), 0),
                }
            )
    return rows


def collect_recognition_listening_probe_exercises(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        generation = record.get("generation")
        probe = generation.get("listening_probe") if isinstance(generation, dict) else None
        if (
            not isinstance(probe, dict)
            or probe.get("version") != RECOGNITION_LISTENING_PROBE_VERSION
        ):
            continue
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            if exercise.get("listening_probe") != RECOGNITION_LISTENING_PROBE_VERSION:
                continue
            condition = exercise.get("listening_condition")
            if condition not in {LISTENING_CONDITION_DEFAULT, LISTENING_CONDITION_TEXTURED}:
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
                    "condition": condition,
                    "s": _coerce_int(exercise.get("s"), 0),
                    "t": _coerce_int(exercise.get("t"), 0),
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


def collect_recognition_rhythm_exercises(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        generation = record.get("generation")
        probe = generation.get("rhythm_probe") if isinstance(generation, dict) else None
        record_audio = record.get("audio")
        record_cadence = (
            _coerce_int(record_audio.get("cadence_variation"), 0)
            if isinstance(record_audio, dict)
            else 0
        )
        baseline_cadence = _coerce_int(
            probe.get("baseline_cadence_variation") if isinstance(probe, dict) else None,
            record_cadence,
        )
        generation_is_tagged = (
            isinstance(probe, dict) and probe.get("version") == RHYTHM_PROBE_VERSION
        )
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
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

            exercise_probe = exercise.get("rhythm_probe")
            cadence_variation = _coerce_int(
                exercise.get("cadence_variation"),
                baseline_cadence,
            )
            is_probe = generation_is_tagged and exercise_probe == RHYTHM_PROBE_VERSION
            rows.append(
                {
                    "condition": "probe" if is_probe else "baseline",
                    "cadence_variation": cadence_variation,
                    "baseline_cadence_variation": baseline_cadence,
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


def recognition_listening_conditions_burden(rows: list[dict[str, Any]]) -> dict[str, Any]:
    default = [row for row in rows if row["condition"] == LISTENING_CONDITION_DEFAULT]
    textured = [row for row in rows if row["condition"] == LISTENING_CONDITION_TEXTURED]
    if not default or not textured:
        return unknown_burden("No controlled default-vs-textured recognition probe yet.")

    default_metrics = recognition_attention_metrics(default)
    textured_metrics = recognition_attention_metrics(textured)
    default_overall = default_metrics.get("overall_fraction")
    textured_overall = textured_metrics.get("overall_fraction")
    confidence = _confidence_from_count(
        min(len(default), len(textured)),
        medium=LISTENING_MIN_EXERCISES_PER_CONDITION,
        high=ATTENTION_MIN_EXERCISES_PER_CONDITION,
    )

    if (
        default_overall is None
        or textured_overall is None
        or len(default) < LISTENING_MIN_EXERCISES_PER_CONDITION
        or len(textured) < LISTENING_MIN_EXERCISES_PER_CONDITION
    ):
        return {
            "debt": DEBT_UNKNOWN,
            "confidence": confidence,
            "evidence": [
                (
                    "Listening-condition probe needs at least "
                    f"{LISTENING_MIN_EXERCISES_PER_CONDITION} default and "
                    f"{LISTENING_MIN_EXERCISES_PER_CONDITION} textured exercises."
                )
            ],
            "default": default_metrics,
            "textured": textured_metrics,
        }

    delta = float(textured_overall) - float(default_overall)
    magnitude = abs(delta)
    if magnitude >= LISTENING_HIGH_DELTA:
        debt = DEBT_HIGH
    elif magnitude >= LISTENING_MODERATE_DELTA:
        debt = DEBT_MODERATE
    else:
        debt = DEBT_LOW

    if delta >= LISTENING_MODERATE_DELTA:
        response = "texture_helped"
        summary = "More textured signal performed better than the default signal"
    elif delta <= -LISTENING_MODERATE_DELTA:
        response = "texture_hurt"
        summary = "More textured signal performed worse than the default signal"
    else:
        response = "neutral"
        summary = "Default and more textured signal performance were similar"

    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": [
            (
                f"{summary}: {_percent(float(textured_overall))} over {len(textured)} "
                f"textured exercises vs {_percent(float(default_overall))} over "
                f"{len(default)} default exercises."
            )
        ],
        "response": response,
        "delta": round(delta, 6),
        "default": default_metrics,
        "textured": textured_metrics,
    }


def koch_listening_conditions_burden(rows: list[dict[str, Any]]) -> dict[str, Any]:
    challenge = [row for row in rows if row.get("probe_phase") == KOCH_PROBE_PHASE_CHALLENGE]
    if challenge:
        metrics = koch_attention_metrics(challenge)
        overall = metrics.get("overall_fraction")
        confidence = _confidence_from_count(
            len(challenge),
            medium=LISTENING_MIN_EXERCISES_PER_CONDITION,
            high=ATTENTION_MIN_EXERCISES_PER_CONDITION,
        )
        if overall is None or len(challenge) < LISTENING_MIN_EXERCISES_PER_CONDITION:
            return {
                "debt": DEBT_UNKNOWN,
                "confidence": confidence,
                "response": "needs_more_challenge_evidence",
                "evidence": [
                    (
                        "Koch listening challenge needs at least "
                        f"{LISTENING_MIN_EXERCISES_PER_CONDITION} saved challenge exercises."
                    )
                ],
                "challenge": metrics,
            }
        if float(overall) >= 0.90:
            debt = DEBT_LOW
            response = "challenge_stable"
        elif float(overall) >= 0.75:
            debt = DEBT_MODERATE
            response = "challenge_mixed"
        else:
            debt = DEBT_HIGH
            response = "challenge_hurt"
        return {
            "debt": debt,
            "confidence": confidence,
            "response": response,
            "evidence": [
                (
                    "Tougher Koch listening challenge: copied "
                    f"{_percent(float(overall))} over {len(challenge)} exercises."
                )
            ],
            "challenge": metrics,
        }

    default = [row for row in rows if row["condition"] == LISTENING_CONDITION_DEFAULT]
    textured = [row for row in rows if row["condition"] == LISTENING_CONDITION_TEXTURED]
    if not default or not textured:
        return unknown_burden("No saved Koch listening challenge evidence yet.")

    default_metrics = koch_attention_metrics(default)
    textured_metrics = koch_attention_metrics(textured)
    default_overall = default_metrics.get("overall_fraction")
    textured_overall = textured_metrics.get("overall_fraction")
    confidence = _confidence_from_count(
        min(len(default), len(textured)),
        medium=LISTENING_MIN_EXERCISES_PER_CONDITION,
        high=ATTENTION_MIN_EXERCISES_PER_CONDITION,
    )

    if (
        default_overall is None
        or textured_overall is None
        or len(default) < LISTENING_MIN_EXERCISES_PER_CONDITION
        or len(textured) < LISTENING_MIN_EXERCISES_PER_CONDITION
    ):
        return {
            "debt": DEBT_UNKNOWN,
            "confidence": confidence,
            "evidence": [
                (
                    "Koch listening-condition probe needs at least "
                    f"{LISTENING_MIN_EXERCISES_PER_CONDITION} default and "
                    f"{LISTENING_MIN_EXERCISES_PER_CONDITION} textured exercises."
                )
            ],
            "default": default_metrics,
            "textured": textured_metrics,
        }

    delta = float(textured_overall) - float(default_overall)
    magnitude = abs(delta)
    if magnitude >= LISTENING_HIGH_DELTA:
        debt = DEBT_HIGH
    elif magnitude >= LISTENING_MODERATE_DELTA:
        debt = DEBT_MODERATE
    else:
        debt = DEBT_LOW

    if delta >= LISTENING_MODERATE_DELTA:
        response = "texture_helped"
        summary = "More textured Koch listening performed better than the default signal"
    elif delta <= -LISTENING_MODERATE_DELTA:
        response = "texture_hurt"
        summary = "More textured Koch listening performed worse than the default signal"
    else:
        response = "neutral"
        summary = "Default and more textured Koch listening performed similarly"

    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": [
            (
                f"{summary}: {_percent(float(textured_overall))} over {len(textured)} "
                f"textured exercises vs {_percent(float(default_overall))} over "
                f"{len(default)} default exercises."
            )
        ],
        "response": response,
        "delta": round(delta, 6),
        "default": default_metrics,
        "textured": textured_metrics,
    }


def recognition_rhythm_burden(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = [row for row in rows if row["condition"] == "baseline"]
    probe = [row for row in rows if row["condition"] == "probe"]
    if not rows:
        return unknown_burden("No saved recognition rhythm evidence yet.")
    baseline_metrics = recognition_attention_metrics(baseline)
    if not probe:
        cadence_levels = sorted({int(row["cadence_variation"]) for row in baseline})
        level_text = (
            ", ".join(str(level) for level in cadence_levels) if cadence_levels else "unknown"
        )
        overall = baseline_metrics.get("overall_fraction")
        percent = _percent(float(overall)) if isinstance(overall, (int, float)) else "unknown"
        return {
            "debt": DEBT_UNKNOWN,
            "confidence": _confidence_from_count(
                len(baseline),
                medium=RHYTHM_MIN_EXERCISES_PER_CONDITION,
                high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
            ),
            "response": "baseline_observed",
            "evidence": [
                (
                    f"Stable rhythm baseline observed at cadence variation {level_text}: "
                    f"{percent} over {len(baseline)} exercises. Higher rhythm variation "
                    "has not been probed yet."
                )
            ],
            "baseline": baseline_metrics,
            "probe": recognition_attention_metrics([]),
        }

    probe_metrics = recognition_attention_metrics(probe)
    baseline_overall = baseline_metrics.get("overall_fraction")
    probe_overall = probe_metrics.get("overall_fraction")
    confidence = _confidence_from_count(
        min(len(baseline), len(probe)),
        medium=RHYTHM_MIN_EXERCISES_PER_CONDITION,
        high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
    )

    if (
        baseline_overall is None
        or probe_overall is None
        or len(baseline) < RHYTHM_MIN_EXERCISES_PER_CONDITION
        or len(probe) < RHYTHM_MIN_EXERCISES_PER_CONDITION
    ):
        return {
            "debt": DEBT_UNKNOWN,
            "confidence": confidence,
            "response": "needs_more_probe_evidence",
            "evidence": [
                (
                    "Rhythm probe needs at least "
                    f"{RHYTHM_MIN_EXERCISES_PER_CONDITION} baseline and "
                    f"{RHYTHM_MIN_EXERCISES_PER_CONDITION} raised-cadence exercises."
                )
            ],
            "baseline": baseline_metrics,
            "probe": probe_metrics,
        }

    delta = float(probe_overall) - float(baseline_overall)
    if delta <= -RHYTHM_HIGH_DELTA:
        debt = DEBT_HIGH
    elif delta <= -RHYTHM_MODERATE_DELTA:
        debt = DEBT_MODERATE
    else:
        debt = DEBT_LOW

    if delta <= -RHYTHM_MODERATE_DELTA:
        response = "rhythm_hurt"
        summary = "Raised rhythm variation performed worse than baseline"
    elif delta >= RHYTHM_MODERATE_DELTA:
        response = "rhythm_helped"
        summary = "Raised rhythm variation performed better than baseline"
    else:
        response = "neutral"
        summary = "Baseline and raised rhythm variation performance were similar"

    probe_levels = sorted({int(row["cadence_variation"]) for row in probe})
    baseline_levels = sorted({int(row["cadence_variation"]) for row in baseline})
    probe_text = ", ".join(str(level) for level in probe_levels) or "unknown"
    baseline_text = ", ".join(str(level) for level in baseline_levels) or "unknown"
    return {
        "debt": debt,
        "confidence": confidence,
        "response": response,
        "delta": round(delta, 6),
        "evidence": [
            (
                f"{summary}: {_percent(float(probe_overall))} over {len(probe)} "
                f"raised-cadence exercises (variation {probe_text}) vs "
                f"{_percent(float(baseline_overall))} over {len(baseline)} "
                f"baseline exercises (variation {baseline_text})."
            )
        ],
        "baseline": baseline_metrics,
        "probe": probe_metrics,
    }


def unknown_burden(evidence: str) -> dict[str, Any]:
    return {
        "debt": DEBT_UNKNOWN,
        "confidence": CONFIDENCE_LOW,
        "evidence": [evidence],
    }


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


def _percent(value: float) -> str:
    return f"{round(value * 100, 1)}%"
