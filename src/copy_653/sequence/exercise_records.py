"""Persisted record builders for Koch Exercise sessions."""

from __future__ import annotations

from typing import Any

from copy_653.sequence.exercise_scoring import (
    ANALYSIS_VERSION,
    _coerce_int,
    _repeat_weight,
    analyse_answer,
    burden_score_for_exercise,
    strip_fixed_anchor,
)

GENERATION_PROFILE_VERSION = "koch-burden-v1"


def build_generation_profile(
    *,
    claimed_set: tuple[str, ...],
    candidate_count: int,
    exercise_count: int,
    gears: list[int] | None = None,
    rst_steps: dict[int, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Build the generation metadata persisted with a Koch record."""
    resolved_gears = gears if gears is not None else [0] * exercise_count
    profile: dict[str, Any] = {
        "profile_version": GENERATION_PROFILE_VERSION,
        "claimed_set_key": " ".join(sorted(claimed_set)),
        "candidate_count": candidate_count,
        "bands": [
            {
                "index": idx + 1,
                "gear": resolved_gears[idx] if idx < len(resolved_gears) else 0,
            }
            for idx in range(exercise_count)
        ],
    }
    if rst_steps:
        profile["rst_steps"] = [
            {"index": band, "s_step": int(s_step), "t_step": int(t_step)}
            for band, (s_step, t_step) in sorted(rst_steps.items())
        ]
    return profile


def build_exercise_entries(
    exercises: list[str],
    *,
    scores: list[int] | tuple[int, ...],
    gears: list[int] | None = None,
    rst_draws: (
        list[tuple[int | None, int | None]] | tuple[tuple[int | None, int | None], ...] | None
    ) = None,
) -> list[dict[str, Any]]:
    """Build persisted per-exercise records before answers are saved."""
    resolved_gears = gears if gears is not None else [0] * len(exercises)
    entries: list[dict[str, Any]] = []
    for idx, played in enumerate(exercises):
        burden_score = scores[idx] if idx < len(scores) else burden_score_for_exercise(played)
        entry: dict[str, Any] = {
            "index": idx + 1,
            "played": played,
            "core": strip_fixed_anchor(played),
            "burden_score": burden_score,
            "burden_band": idx + 1,
            "gear": resolved_gears[idx] if idx < len(resolved_gears) else 0,
            "answer": "",
            "analysis": {
                "version": ANALYSIS_VERSION,
                "saved": False,
            },
        }
        if rst_draws is not None and idx < len(rst_draws):
            s_draw, t_draw = rst_draws[idx]
            if s_draw is not None:
                entry["s"] = int(s_draw)
            if t_draw is not None:
                entry["t"] = int(t_draw)
        entries.append(entry)
    return entries


def apply_answers_to_entries(
    entries: list[dict[str, Any]],
    answers: list[str],
    *,
    claimed_set_size: int,
) -> list[dict[str, Any]]:
    """Return entries with saved answers and internal analysis merged in."""
    if len(answers) != len(entries):
        raise ValueError(
            f"answers length {len(answers)} does not match exercises length {len(entries)}"
        )

    updated: list[dict[str, Any]] = []
    seen_cores: dict[str, int] = {}
    for idx, (entry, answer) in enumerate(zip(entries, answers), start=1):
        played = str(entry.get("played", ""))
        core = str(entry.get("core") or strip_fixed_anchor(played))
        seen_cores[core] = seen_cores.get(core, 0) + 1
        burden_score = _coerce_int(entry.get("burden_score"), burden_score_for_exercise(played))
        burden_band = _coerce_int(entry.get("burden_band"), idx)
        gear = _coerce_int(entry.get("gear"), 0)
        merged = dict(entry)
        merged["answer"] = answer
        merged["analysis"] = analyse_answer(
            played=played,
            answer=answer,
            exercise_index=idx,
            burden_score=burden_score,
            burden_band=burden_band,
            gear=gear,
            claimed_set_size=claimed_set_size,
            repeat_weight=_repeat_weight(seen_cores[core]),
        )
        updated.append(merged)
    return updated
