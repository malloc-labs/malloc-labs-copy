"""Confusion aggregation for saved Symbol Recognition sessions."""

from __future__ import annotations

from typing import Any

from copy_653.sequence.exercise_analysis import record_claimed_set_key
from copy_653.sequence.recognition_review import recognition_review_analysis

CONFUSION_TREND_SESSION_WINDOW = 20
CONFUSION_TREND_MIN_DELTA = 0.05


def load_recognition_confusion(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    trend_window_size: int = CONFUSION_TREND_SESSION_WINDOW,
) -> dict[str, Any]:
    """Aggregate both confusion streams across recognition sessions.

    Walks every recognition record whose claimed-set identity matches
    ``claimed_set_key`` and sums the per-exercise ``analysis`` blocks
    written at save time. The two streams stay separate:

    * ``committed_substitutions`` -- truth -> what the learner committed.
    * ``caught_substitutions`` -- truth -> a false start they superseded
      before committing.

    A caught confusion is never folded into the committed count. Only
    exercises with ``has_evidence`` contribute.
    """
    matching = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("mode") == "recognition"
        and record_claimed_set_key(record) == claimed_set_key
    ]
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    window_size = max(0, trend_window_size)
    recent = matching[:window_size]
    previous = matching[window_size : window_size * 2]

    lifetime_stats = _recognition_confusion_stats(matching)
    recent_stats = _recognition_confusion_stats(recent)
    previous_stats = _recognition_confusion_stats(previous)

    return {
        "claimed_set_key": claimed_set_key,
        "exercises_used": lifetime_stats["exercises_used"],
        "trend_window_size": window_size,
        "recent_exercises_used": recent_stats["exercises_used"],
        "previous_exercises_used": previous_stats["exercises_used"],
        "committed_substitutions": _sorted_pairs_with_trend(
            lifetime_stats["committed"],
            recent_stats,
            previous_stats,
            stream="committed",
        ),
        "caught_substitutions": _sorted_pairs_with_trend(
            lifetime_stats["caught"],
            recent_stats,
            previous_stats,
            stream="caught",
        ),
    }


def _recognition_confusion_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    committed: dict[tuple[str, str], int] = {}
    caught: dict[tuple[str, str], int] = {}
    target_exposures: dict[str, int] = {}
    exercises_used = 0

    for record in records:
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = _review_analysis_for_exercise(exercise)
            if not isinstance(analysis, dict) or analysis.get("has_evidence") is not True:
                continue
            exercises_used += 1
            for target in _analysis_slot_truths(analysis):
                target_exposures[target] = target_exposures.get(target, 0) + 1
            for pair in analysis.get("committed_confusions") or []:
                _tally_pair(committed, pair)
            for pair in analysis.get("caught_confusions") or []:
                _tally_pair(caught, pair)

    return {
        "committed": committed,
        "caught": caught,
        "target_exposures": target_exposures,
        "exercises_used": exercises_used,
    }


def _review_analysis_for_exercise(exercise: dict[str, Any]) -> dict[str, Any]:
    review = exercise.get("review_analysis")
    if isinstance(review, dict):
        return review
    return recognition_review_analysis(exercise)


def _analysis_slot_truths(analysis: dict[str, Any]) -> list[str]:
    truths: list[str] = []
    slots = analysis.get("slots")
    if not isinstance(slots, list):
        return truths
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        truth = slot.get("truth")
        if isinstance(truth, str) and truth:
            truths.append(truth.upper())
    return truths


def _sorted_pairs_with_trend(
    lifetime: dict[tuple[str, str], int],
    recent_stats: dict[str, Any],
    previous_stats: dict[str, Any],
    *,
    stream: str,
) -> list[dict[str, Any]]:
    recent = recent_stats[stream]
    previous = previous_stats[stream]
    recent_exposures = recent_stats["target_exposures"]
    previous_exposures = previous_stats["target_exposures"]
    rows: list[dict[str, Any]] = []
    for pair, count in lifetime.items():
        target, typed = pair
        recent_count = recent.get(pair, 0)
        previous_count = previous.get(pair, 0)
        recent_total = recent_exposures.get(target, 0)
        previous_total = previous_exposures.get(target, 0)
        recent_rate = _rate(recent_count, recent_total)
        previous_rate = _rate(previous_count, previous_total)
        rows.append(
            {
                "target": target,
                "typed": typed,
                "count": count,
                "recent_count": recent_count,
                "recent_total": recent_total,
                "recent_rate": recent_rate,
                "previous_count": previous_count,
                "previous_total": previous_total,
                "previous_rate": previous_rate,
                "trend": _confusion_trend(recent_rate, previous_rate),
            }
        )
    rows.sort(key=lambda item: (-item["count"], item["target"], item["typed"]))
    return rows


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 6)


def _confusion_trend(recent_rate: float | None, previous_rate: float | None) -> str:
    if recent_rate is None or previous_rate is None:
        return "insufficient"
    delta = recent_rate - previous_rate
    if delta <= -CONFUSION_TREND_MIN_DELTA:
        return "improving"
    if delta >= CONFUSION_TREND_MIN_DELTA:
        return "worsening"
    return "stable"


def _tally_pair(counter: dict[tuple[str, str], int], pair: Any) -> None:
    """Increment ``(target, typed)`` if ``pair`` is a well-formed string pair."""
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return
    target, typed = pair
    if not isinstance(target, str) or not isinstance(typed, str):
        return
    counter[(target, typed)] = counter.get((target, typed), 0) + 1
