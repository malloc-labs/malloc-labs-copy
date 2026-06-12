"""Symbol confusion aggregation for saved Koch Exercise sessions."""

from __future__ import annotations

from typing import Any

from copy_653.sequence.exercise_progression import _matching_sessions
from copy_653.sequence.exercise_scoring import _align, _symbols_only, strip_fixed_anchor


def load_confusion_pairs(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
) -> dict[str, Any]:
    """Per-symbol confusion counts across all sessions for one claimed set."""
    substitutions: dict[tuple[str, str], int] = {}
    exercises_used = 0

    for record in _matching_sessions(records, claimed_set_key, exclude_warmup=False):
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
            exercises_used += 1
            for op, t_ch, a_ch in _align(truth, typed):
                if op == "sub":
                    substitutions[(t_ch, a_ch)] = substitutions.get((t_ch, a_ch), 0) + 1

    pairs = sorted(
        [{"target": t, "typed": a, "count": c} for (t, a), c in substitutions.items()],
        key=lambda p: (-p["count"], p["target"], p["typed"]),
    )

    return {
        "claimed_set_key": claimed_set_key,
        "exercises_used": exercises_used,
        "substitutions": pairs,
    }
