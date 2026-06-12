"""RST sub-axis progression for Koch Exercise sessions."""

from __future__ import annotations

from typing import Any, Callable

from copy_653.sequence.exercise_progression import (
    DEFAULT_EVIDENCE_WINDOW_SIZE,
    LOW_FRACTION,
    MAX_GEAR,
    N_CLEAN_RUNS_FOR_SHIFT,
    STRONG_FRACTION,
    _exercise_gear,
    _gears_from_generation,
    _matching_sessions,
)

N_LOW_RUNS_FOR_RST_STEP_DOWN = 2
MAX_RST_STEP = 5
RST_WINDOW_WIDTH = 3
RST_WINDOW_TOP = 9


def rst_window_for_step(step: int) -> tuple[int, int]:
    """Return the inclusive (lo, hi) RST draw window for a sub-axis step."""
    clamped = max(0, min(MAX_RST_STEP, int(step)))
    hi = RST_WINDOW_TOP - clamped
    lo = hi - RST_WINDOW_WIDTH + 1
    return lo, hi


def is_eligible_for_axis(drawn: int, step: int) -> bool:
    """Whether a drawn S or T value sits at the bottom of its step's window."""
    lo, _ = rst_window_for_step(step)
    return int(drawn) == lo


def _rst_steps_from_generation(generation: Any) -> dict[int, tuple[int, int]]:
    """Extract ``{burden_band: (s_step, t_step)}`` from a generation profile."""
    if not isinstance(generation, dict):
        return {}
    entries = generation.get("rst_steps")
    if not isinstance(entries, list):
        return {}
    out: dict[int, tuple[int, int]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        s_step = entry.get("s_step")
        t_step = entry.get("t_step")
        if (
            isinstance(idx, int)
            and not isinstance(idx, bool)
            and isinstance(s_step, int)
            and not isinstance(s_step, bool)
            and isinstance(t_step, int)
            and not isinstance(t_step, bool)
        ):
            out[idx] = (s_step, t_step)
    return out


def latest_rst_steps_for_claimed_set(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
) -> dict[int, tuple[int, int]]:
    """Per-band ``(s_step, t_step)`` from the most recent matching session."""
    matching = _matching_sessions(records, claimed_set_key)
    if not matching:
        return {}
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return _rst_steps_from_generation(matching[0].get("generation"))


def _exercise_rst_draw(exercise: Any) -> tuple[int | None, int | None]:
    """Read per-exercise ``(s, t)`` draws if present and well-typed."""
    if not isinstance(exercise, dict):
        return None, None
    raw_s = exercise.get("s")
    raw_t = exercise.get("t")
    s = raw_s if isinstance(raw_s, int) and not isinstance(raw_s, bool) else None
    t = raw_t if isinstance(raw_t, int) and not isinstance(raw_t, bool) else None
    return s, t


def _step_axis_streak(
    entries: list[tuple[float, int]],
    predicate: Callable[[float], bool],
) -> int:
    """Streak of newest-first entries matching ``predicate`` at the current step."""
    count = 0
    current_step: int | None = None
    for fraction, step in entries:
        if current_step is None:
            current_step = step
        elif step != current_step:
            return count
        if not predicate(fraction):
            return count
        count += 1
    return count


def load_rst_axis_evidence(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_EVIDENCE_WINDOW_SIZE,
) -> dict[str, Any]:
    """Per-band per-axis evidence at gear ``MAX_GEAR`` for the RST sub-axis."""
    matching = _matching_sessions(records, claimed_set_key)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)

    s_entries: dict[int, list[tuple[float, int]]] = {}
    t_entries: dict[int, list[tuple[float, int]]] = {}

    for session in matching:
        generation = session.get("generation")
        session_gears = _gears_from_generation(generation)
        session_steps = _rst_steps_from_generation(generation)
        exercises = session.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("saved") is not True:
                continue
            burden_band = exercise.get("burden_band")
            if not isinstance(burden_band, int) or isinstance(burden_band, bool):
                continue
            gear = _exercise_gear(exercise, session_gears, burden_band)
            if gear != MAX_GEAR:
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            if burden_band not in session_steps:
                continue
            s_step, t_step = session_steps[burden_band]
            drawn_s, drawn_t = _exercise_rst_draw(exercise)
            if drawn_s is not None and is_eligible_for_axis(drawn_s, s_step):
                bucket = s_entries.setdefault(burden_band, [])
                if len(bucket) < window_size:
                    bucket.append((float(fraction), s_step))
            if drawn_t is not None and is_eligible_for_axis(drawn_t, t_step):
                bucket = t_entries.setdefault(burden_band, [])
                if len(bucket) < window_size:
                    bucket.append((float(fraction), t_step))

    bands_out: list[dict[str, Any]] = []
    for band_index in sorted(set(s_entries) | set(t_entries)):
        s_list = s_entries.get(band_index, [])
        t_list = t_entries.get(band_index, [])
        bands_out.append(
            {
                "burden_band": band_index,
                "s_axis": {
                    "recent_fractions": [round(f, 6) for f, _ in s_list],
                    "strong_streak": _step_axis_streak(s_list, lambda v: v >= STRONG_FRACTION),
                    "low_streak": _step_axis_streak(s_list, lambda v: v < LOW_FRACTION),
                },
                "t_axis": {
                    "recent_fractions": [round(f, 6) for f, _ in t_list],
                    "strong_streak": _step_axis_streak(t_list, lambda v: v >= STRONG_FRACTION),
                    "low_streak": _step_axis_streak(t_list, lambda v: v < LOW_FRACTION),
                },
            }
        )

    return {
        "claimed_set_key": claimed_set_key,
        "window_size": window_size,
        "bands": bands_out,
    }


def _shift_step(
    current: int,
    axis_evidence: Any,
    *,
    max_step: int,
    n_clean: int,
    n_low: int,
) -> int:
    axis = axis_evidence if isinstance(axis_evidence, dict) else {}
    strong_streak = axis.get("strong_streak", 0)
    low_streak = axis.get("low_streak", 0)
    if isinstance(strong_streak, int) and strong_streak >= n_clean and current < max_step:
        return current + 1
    if isinstance(low_streak, int) and low_streak >= n_low and current > 0:
        return current - 1
    return current


def resolve_rst_steps(
    axis_evidence: dict[str, Any],
    *,
    current_steps: dict[int, tuple[int, int]],
    max_step: int = MAX_RST_STEP,
    n_clean_runs_for_shift: int = N_CLEAN_RUNS_FOR_SHIFT,
    n_low_runs_for_shift_down: int = N_LOW_RUNS_FOR_RST_STEP_DOWN,
) -> dict[int, tuple[int, int]]:
    """Per-band ``(s_step, t_step)`` for the next session."""
    resolved: dict[int, tuple[int, int]] = dict(current_steps)
    for band in axis_evidence.get("bands") or []:
        if not isinstance(band, dict):
            continue
        burden_band = band.get("burden_band")
        if not isinstance(burden_band, int) or isinstance(burden_band, bool):
            continue
        cur_s, cur_t = resolved.get(burden_band, (0, 0))
        new_s = _shift_step(
            cur_s,
            band.get("s_axis"),
            max_step=max_step,
            n_clean=n_clean_runs_for_shift,
            n_low=n_low_runs_for_shift_down,
        )
        new_t = _shift_step(
            cur_t,
            band.get("t_axis"),
            max_step=max_step,
            n_clean=n_clean_runs_for_shift,
            n_low=n_low_runs_for_shift_down,
        )
        resolved[burden_band] = (new_s, new_t)
    return resolved
