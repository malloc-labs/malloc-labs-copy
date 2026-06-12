"""Gear evidence, history, and readiness for Koch Exercise sessions."""

from __future__ import annotations

from typing import Any, Callable

from copy_653.sequence.listening_conditions import KOCH_PROGRESSION_ROLE_SUPPORTING_GEAR_UP

DEFAULT_EVIDENCE_WINDOW_SIZE = 5
STRONG_FRACTION = 0.95
LOW_FRACTION = 0.70
MAX_GEAR = 3
MAX_CONTENT_GEAR = 2
N_CLEAN_RUNS_FOR_SHIFT = 3
N_LOW_RUNS_FOR_SHIFT_DOWN = 4


def record_claimed_set_key(record: dict[str, Any]) -> str:
    """Return the claimed-set identity for a saved koch-exercise record."""
    generation = record.get("generation")
    if isinstance(generation, dict):
        stored = generation.get("claimed_set_key")
        if isinstance(stored, str):
            return stored
    claimed = record.get("claimed_set")
    if isinstance(claimed, list):
        return " ".join(sorted(str(s) for s in claimed))
    return ""


def _matching_sessions(
    records: list[dict[str, Any]],
    claimed_set_key: str,
    *,
    exclude_warmup: bool = True,
) -> list[dict[str, Any]]:
    """Filter records to koch-exercise sessions matching one claimed set."""
    matching: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("mode") != "koch-exercise":
            continue
        if exclude_warmup and record.get("warm_up") is True:
            continue
        if record_claimed_set_key(record) != claimed_set_key:
            continue
        matching.append(record)
    return matching


def _exercise_gear(
    exercise: dict[str, Any],
    session_gears: dict[int, int],
    burden_band: int,
) -> int:
    """Resolve the gear for one exercise, preferring the generation profile."""
    gear = session_gears.get(burden_band)
    if gear is not None:
        return gear
    raw_gear = exercise.get("gear", 0)
    return raw_gear if isinstance(raw_gear, int) and not isinstance(raw_gear, bool) else 0


def load_band_evidence(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_EVIDENCE_WINDOW_SIZE,
) -> dict[str, Any]:
    """Aggregate per-band evidence over recent sessions for one claimed set."""
    matching = _matching_sessions(records, claimed_set_key)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    normal_matching = [
        session for session in matching if not _is_supporting_gear_up_session(session)
    ]
    window = normal_matching[: max(0, window_size)]
    challenge_window = matching[: max(0, window_size)]

    band_entries: dict[int, list[tuple[float, str, int]]] = {}
    challenge_support: dict[int, int] = {}
    for session in window:
        session_gears = _gears_from_generation(session.get("generation"))
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
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            state = analysis.get("band_state")
            gear = _exercise_gear(exercise, session_gears, burden_band)
            band_entries.setdefault(burden_band, []).append(
                (
                    float(fraction),
                    str(state) if isinstance(state, str) else "",
                    gear,
                )
            )

    for session in challenge_window:
        if not _is_supporting_gear_up_session(session):
            continue
        session_gears = _gears_from_generation(session.get("generation"))
        exercises = session.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            if exercise.get("progression_role") != KOCH_PROGRESSION_ROLE_SUPPORTING_GEAR_UP:
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("saved") is not True:
                continue
            burden_band = exercise.get("burden_band")
            if not isinstance(burden_band, int) or isinstance(burden_band, bool):
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            if _exercise_gear(exercise, session_gears, burden_band) < MAX_GEAR:
                continue
            if float(fraction) >= STRONG_FRACTION:
                challenge_support[burden_band] = challenge_support.get(burden_band, 0) + 1

    bands: list[dict[str, Any]] = []
    for band_index in sorted(set(band_entries) | set(challenge_support)):
        entries = band_entries.get(band_index, [])
        if not entries:
            continue
        fractions = [f for f, _, _ in entries]
        states = [s for _, s, _ in entries]
        bands.append(
            {
                "burden_band": band_index,
                "current_gear": entries[0][2],
                "recent_fractions": [round(f, 6) for f in fractions],
                "recent_band_states": states,
                "strong_streak": _streak_at_current_gear(entries, lambda v: v >= STRONG_FRACTION),
                "low_streak": _streak_at_current_gear(entries, lambda v: v < LOW_FRACTION),
                "challenge_support_strong": challenge_support.get(band_index, 0),
            }
        )

    return {
        "claimed_set_key": claimed_set_key,
        "session_count": len(matching),
        "window_size": window_size,
        "sessions_used": len(window),
        "bands": bands,
    }


def _streak_at_current_gear(
    entries: list[tuple[float, str, int]],
    predicate: Callable[[float], bool],
) -> int:
    """Streak of consecutive entries matching ``predicate`` at the current gear."""
    count = 0
    current_gear: int | None = None
    for fraction, _state, gear in entries:
        if current_gear is None:
            current_gear = gear
        elif gear != current_gear:
            return count
        if not predicate(fraction):
            return count
        count += 1
    return count


def _is_supporting_gear_up_session(record: dict[str, Any]) -> bool:
    generation = record.get("generation")
    if not isinstance(generation, dict):
        return False
    return generation.get("progression_role") == KOCH_PROGRESSION_ROLE_SUPPORTING_GEAR_UP


def _gears_from_generation(generation: Any) -> dict[int, int]:
    """Extract ``{index: gear}`` from a generation profile dict."""
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
        gear = entry.get("gear", 0)
        if (
            isinstance(idx, int)
            and not isinstance(idx, bool)
            and isinstance(gear, int)
            and not isinstance(gear, bool)
        ):
            out[idx] = gear
    return out


def latest_gears_for_claimed_set(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
) -> dict[int, int]:
    """Return the per-band gears from the most recent matching session."""
    matching = _matching_sessions(records, claimed_set_key)
    matching = [record for record in matching if not _is_supporting_gear_up_session(record)]
    if not matching:
        return {}
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return _gears_from_generation(matching[0].get("generation"))


def load_band_history(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
) -> dict[str, Any]:
    """Chronological per-band history for one claimed-set key."""
    matching = _matching_sessions(records, claimed_set_key)
    matching.sort(key=lambda r: str(r.get("started_at") or ""))

    sessions_meta: list[dict[str, Any]] = []
    for chronological_index, record in enumerate(matching, start=1):
        generation = record.get("generation")
        run_index: int | None = None
        if isinstance(generation, dict):
            stored = generation.get("run_index")
            if isinstance(stored, int) and not isinstance(stored, bool):
                run_index = stored
        sessions_meta.append(
            {
                "run_index": run_index if run_index is not None else chronological_index,
                "started_at": str(record.get("started_at") or ""),
            }
        )

    band_entries: dict[int, list[dict[str, Any]]] = {}
    for idx, record in enumerate(matching):
        run_index = sessions_meta[idx]["run_index"]
        started_at = sessions_meta[idx]["started_at"]
        session_gears = _gears_from_generation(record.get("generation"))

        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            burden_band = exercise.get("burden_band")
            if not isinstance(burden_band, int) or isinstance(burden_band, bool):
                continue

            analysis = exercise.get("analysis")
            fraction: float | None = None
            state = ""
            if isinstance(analysis, dict) and analysis.get("saved") is True:
                raw_fraction = analysis.get("combined_fraction")
                if isinstance(raw_fraction, (int, float)) and not isinstance(raw_fraction, bool):
                    fraction = round(float(raw_fraction), 6)
                raw_state = analysis.get("band_state")
                state = str(raw_state) if isinstance(raw_state, str) else ""

            gear = _exercise_gear(exercise, session_gears, burden_band)

            band_entries.setdefault(burden_band, []).append(
                {
                    "run_index": run_index,
                    "started_at": started_at,
                    "fraction": fraction,
                    "gear": gear,
                    "band_state": state,
                }
            )

    gear_changes: list[dict[str, Any]] = []
    for burden_band, entries in band_entries.items():
        prev_gear: int | None = None
        for entry in entries:
            current_gear = entry["gear"]
            if prev_gear is not None and current_gear != prev_gear:
                gear_changes.append(
                    {
                        "burden_band": burden_band,
                        "run_index": entry["run_index"],
                        "started_at": entry["started_at"],
                        "previous_gear": prev_gear,
                        "current_gear": current_gear,
                    }
                )
            prev_gear = current_gear
    gear_changes.sort(key=lambda c: (c["run_index"], c["burden_band"]))

    current_gears = _gears_from_generation(matching[-1].get("generation")) if matching else {}

    return {
        "claimed_set_key": claimed_set_key,
        "session_count": len(matching),
        "sessions": sessions_meta,
        "bands": [
            {"burden_band": band, "entries": entries}
            for band, entries in sorted(band_entries.items())
        ],
        "gear_changes": gear_changes,
        "current_gears": dict(sorted(current_gears.items())),
    }


def is_ready_for_next_symbol(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    strong_fraction: float = STRONG_FRACTION,
    n_strong_required: int = N_CLEAN_RUNS_FOR_SHIFT,
    max_gear: int = MAX_GEAR,
    window_size: int = DEFAULT_EVIDENCE_WINDOW_SIZE,
) -> bool:
    """Whether the learner is ready for the next-symbol suggestion."""
    if not claimed_set_key:
        return False

    current_gears = latest_gears_for_claimed_set(records, claimed_set_key=claimed_set_key)
    if not current_gears:
        return False
    if any(gear < max_gear for gear in current_gears.values()):
        return False

    evidence = load_band_evidence(
        records,
        claimed_set_key=claimed_set_key,
        window_size=window_size,
    )
    band_evidence = evidence.get("bands") or []
    if len(band_evidence) != len(current_gears):
        return False

    for band in band_evidence:
        fractions = band.get("recent_fractions") or []
        if not fractions:
            return False
        if fractions[0] < strong_fraction:
            return False
        strong_count = sum(1 for f in fractions if f >= strong_fraction)
        if strong_count < n_strong_required:
            return False

    return True


def resolve_gears(
    evidence: dict[str, Any],
    *,
    current_gears: dict[int, int],
    max_gear: int = MAX_GEAR,
    n_clean_runs_for_shift: int = N_CLEAN_RUNS_FOR_SHIFT,
    n_low_runs_for_shift_down: int = N_LOW_RUNS_FOR_SHIFT_DOWN,
) -> dict[int, int]:
    """Compute per-band gear assignments for the next session."""
    resolved: dict[int, int] = dict(current_gears)
    for band in evidence.get("bands") or []:
        if not isinstance(band, dict):
            continue
        burden_band = band.get("burden_band")
        if not isinstance(burden_band, int) or isinstance(burden_band, bool):
            continue
        current = resolved.get(burden_band, 0)
        strong_streak = band.get("strong_streak", 0)
        low_streak = band.get("low_streak", 0)
        challenge_support = band.get("challenge_support_strong", 0)
        if (
            isinstance(strong_streak, int)
            and (
                strong_streak >= n_clean_runs_for_shift
                or (
                    strong_streak >= n_clean_runs_for_shift - 1
                    and isinstance(challenge_support, int)
                    and challenge_support > 0
                )
            )
            and current < max_gear
        ):
            resolved[burden_band] = current + 1
        elif (
            isinstance(low_streak, int) and low_streak >= n_low_runs_for_shift_down and current > 0
        ):
            resolved[burden_band] = current - 1
        else:
            resolved[burden_band] = current
    return resolved
