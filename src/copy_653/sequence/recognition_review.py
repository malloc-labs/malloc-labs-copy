"""Review-time recovery softening for Symbol Recognition analysis."""

from __future__ import annotations

from typing import Any

from copy_653.sequence.recognition_windowing import (
    OUTCOME_CAUGHT_CORRECT,
    OUTCOME_CAUGHT_SUBSTITUTION,
    OUTCOME_SUBSTITUTION,
)

REVIEW_ANALYSIS_VERSION = "recognition-review-v1"


def recognition_review_analysis(exercise: dict[str, Any]) -> dict[str, Any]:
    """Return a settings-only analysis view with recovered errors softened.

    The saved ``analysis`` block remains the strict answer-aligned result used
    by exercise repeat/progression policy. Review screens have more evidence:
    if strict alignment reports substitutions but the timing reconstruction
    shows caught/recovery activity, treat those substitutions as recovered
    rather than committed hard confusions. The exercise is still not exact; this
    only keeps retrospective analytics from counting plausible self-correction
    as ordinary hard substitution debt.
    """
    analysis = exercise.get("analysis")
    if not isinstance(analysis, dict):
        return {}

    review = _clone_analysis(analysis)
    review["review_version"] = REVIEW_ANALYSIS_VERSION
    review["review_method"] = "strict-with-recovery-softening"
    review["recovery_softened"] = False
    review["softened_substitutions"] = 0

    counts = review.get("counts")
    if not isinstance(counts, dict):
        return review
    substitutions = counts.get(OUTCOME_SUBSTITUTION)
    if not isinstance(substitutions, int) or isinstance(substitutions, bool) or substitutions <= 0:
        return review

    timing = exercise.get("timing_analysis")
    if not _timing_has_recovery_evidence(timing):
        return review

    counts[OUTCOME_SUBSTITUTION] = 0
    counts[OUTCOME_CAUGHT_SUBSTITUTION] = (
        _count_value(counts.get(OUTCOME_CAUGHT_SUBSTITUTION)) + substitutions
    )
    review["recovery_softened"] = True
    review["softened_substitutions"] = substitutions
    review["softened_committed_confusions"] = [
        list(pair) for pair in review.get("committed_confusions") or []
    ]
    review["committed_confusions"] = []
    review["caught_confusions"] = _combined_confusion_pairs(
        review.get("caught_confusions"),
        timing.get("caught_confusions") if isinstance(timing, dict) else None,
    )
    return review


def attach_recognition_review_analysis(record: dict[str, Any]) -> dict[str, Any]:
    """Attach settings-only ``review_analysis`` blocks to a recognition record."""
    updated = dict(record)
    exercises = record.get("exercises")
    if not isinstance(exercises, list):
        return updated

    updated_exercises: list[Any] = []
    for exercise in exercises:
        if not isinstance(exercise, dict):
            updated_exercises.append(exercise)
            continue
        merged = dict(exercise)
        review = recognition_review_analysis(exercise)
        if review:
            merged["review_analysis"] = review
        updated_exercises.append(merged)
    updated["exercises"] = updated_exercises
    return updated


def _clone_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(analysis)
    counts = analysis.get("counts")
    if isinstance(counts, dict):
        cloned["counts"] = dict(counts)
    slots = analysis.get("slots")
    if isinstance(slots, list):
        cloned["slots"] = [dict(slot) if isinstance(slot, dict) else slot for slot in slots]
    for key in ("committed_confusions", "caught_confusions"):
        cloned[key] = [list(pair) for pair in analysis.get(key) or []]
    return cloned


def _timing_has_recovery_evidence(timing: Any) -> bool:
    if not isinstance(timing, dict) or timing.get("has_evidence") is not True:
        return False
    caught = timing.get("caught_confusions")
    if isinstance(caught, list) and any(_valid_pair(pair) is not None for pair in caught):
        return True
    counts = timing.get("counts")
    if not isinstance(counts, dict):
        return False
    return (
        _count_value(counts.get(OUTCOME_CAUGHT_CORRECT))
        + _count_value(counts.get(OUTCOME_CAUGHT_SUBSTITUTION))
        > 0
    )


def _combined_confusion_pairs(*sources: Any) -> list[list[str]]:
    pairs: list[list[str]] = []
    for source in sources:
        if not isinstance(source, list):
            continue
        for pair in source:
            valid = _valid_pair(pair)
            if valid is not None:
                pairs.append(valid)
    return pairs


def _valid_pair(pair: Any) -> list[str] | None:
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None
    target, typed = pair
    if not isinstance(target, str) or not isinstance(typed, str):
        return None
    if not target or not typed:
        return None
    return [target, typed]


def _count_value(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
