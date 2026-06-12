"""Progression and gear evidence for saved Symbol Recognition sessions."""

from __future__ import annotations

from typing import Any

from copy_653.sequence.exercise_analysis import (
    DEFAULT_EVIDENCE_WINDOW_SIZE,
    LOW_FRACTION,
    MAX_GEAR,
    N_CLEAN_RUNS_FOR_SHIFT,
    N_LOW_RUNS_FOR_SHIFT_DOWN,
    STRONG_FRACTION,
    _streak_at_current_gear,
    record_claimed_set_key,
)

GENERATION_PROFILE_VERSION = "recognition-progression-v1"
RECOGNITION_SET_SIZE = 8

# Recognition set-level progression already waits for 8 sessions before
# deciding. One strong completed set can move up; two low completed sets
# are required to move down so the first harder set can be adaptation.
N_LOW_SETS_FOR_RECOGNITION_SHIFT_DOWN = 2
N_LOW_RUNS_FOR_RECOGNITION_SHIFT_DOWN = N_LOW_RUNS_FOR_SHIFT_DOWN


def build_recognition_generation_profile(
    *,
    claimed_set: tuple[str, ...],
    exercise_count: int,
    gears: list[int] | None = None,
) -> dict[str, Any]:
    """Build Recognition generation metadata with one set-level gear."""
    resolved_gears = gears if gears is not None else [0] * exercise_count
    set_gear = resolved_gears[0] if resolved_gears else 0
    return {
        "profile_version": GENERATION_PROFILE_VERSION,
        "claimed_set_key": " ".join(sorted(claimed_set)),
        "exercise_count": exercise_count,
        "gear": set_gear,
        "bands": [
            {
                "index": idx + 1,
                "gear": resolved_gears[idx] if idx < len(resolved_gears) else 0,
            }
            for idx in range(exercise_count)
        ],
    }


def load_set_evidence(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    set_size: int = RECOGNITION_SET_SIZE,
    window_size: int = DEFAULT_EVIDENCE_WINDOW_SIZE,
) -> dict[str, Any]:
    """Aggregate completed Recognition sets as progression evidence."""
    completed = _completed_sets(records, claimed_set_key=claimed_set_key, set_size=set_size)
    window = completed[: max(0, window_size)]
    entries = [(item["fraction"], item["state"], item["gear"]) for item in window]

    return {
        "claimed_set_key": claimed_set_key,
        "set_count": len(completed),
        "window_size": window_size,
        "sets_used": len(window),
        "recent_fractions": [round(fraction, 6) for fraction, _state, _gear in entries],
        "recent_states": [state for _fraction, state, _gear in entries],
        "recent_gears": [gear for _fraction, _state, gear in entries],
        "strong_streak": _streak_at_current_gear(entries, lambda v: v >= STRONG_FRACTION),
        "low_streak": _streak_at_current_gear(entries, lambda v: v < LOW_FRACTION),
    }


def latest_completed_set_gear_for_claimed_set(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    set_size: int = RECOGNITION_SET_SIZE,
) -> int:
    completed = _completed_sets(records, claimed_set_key=claimed_set_key, set_size=set_size)
    return completed[0]["gear"] if completed else 0


def gear_for_recognition_set(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    set_id: str,
) -> int | None:
    matching = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("mode") == "recognition"
        and record_claimed_set_key(record) == claimed_set_key
        and _record_set_id(record) == set_id
    ]
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    for record in matching:
        gear = _gear_from_generation(record.get("generation"))
        if gear is not None:
            return gear
    return None


def resolve_set_gear(
    evidence: dict[str, Any],
    *,
    current_gear: int,
    max_gear: int = MAX_GEAR,
    n_clean_sets_for_shift: int = 1,
    n_low_sets_for_shift_down: int = N_LOW_SETS_FOR_RECOGNITION_SHIFT_DOWN,
) -> int:
    strong_streak = evidence.get("strong_streak", 0)
    low_streak = evidence.get("low_streak", 0)
    if (
        isinstance(strong_streak, int)
        and strong_streak >= n_clean_sets_for_shift
        and current_gear < max_gear
    ):
        return current_gear + 1
    if isinstance(low_streak, int) and low_streak >= n_low_sets_for_shift_down and current_gear > 0:
        return current_gear - 1
    return current_gear


def load_band_evidence(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_EVIDENCE_WINDOW_SIZE,
) -> dict[str, Any]:
    """Aggregate recent Recognition evidence by exercise slot."""
    matching = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("mode") == "recognition"
        and record_claimed_set_key(record) == claimed_set_key
    ]
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    window = matching[: max(0, window_size)]

    band_entries: dict[int, list[tuple[float, str, int]]] = {}
    for session in window:
        session_gears = _gears_from_generation(session.get("generation"))
        exercises = session.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict):
                continue
            band = exercise.get("burden_band")
            if not isinstance(band, int) or isinstance(band, bool):
                band = exercise.get("index")
            if not isinstance(band, int) or isinstance(band, bool):
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            state = analysis.get("recognition_state") or analysis.get("band_state") or ""
            gear = session_gears.get(band, _coerce_int(exercise.get("gear"), 0))
            band_entries.setdefault(band, []).append((float(fraction), str(state), gear))

    bands: list[dict[str, Any]] = []
    for band_index in sorted(band_entries):
        entries = band_entries[band_index]
        bands.append(
            {
                "burden_band": band_index,
                "recent_fractions": [round(f, 6) for f, _, _ in entries],
                "recent_band_states": [s for _, s, _ in entries],
                "strong_streak": _streak_at_current_gear(
                    entries,
                    lambda v: v >= STRONG_FRACTION,
                ),
                "low_streak": _streak_at_current_gear(entries, lambda v: v < LOW_FRACTION),
            }
        )

    return {
        "claimed_set_key": claimed_set_key,
        "session_count": len(matching),
        "window_size": window_size,
        "sessions_used": len(window),
        "bands": bands,
    }


def latest_gears_for_claimed_set(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
) -> dict[int, int]:
    matching = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("mode") == "recognition"
        and record_claimed_set_key(record) == claimed_set_key
    ]
    if not matching:
        return {}
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return _gears_from_generation(matching[0].get("generation"))


def resolve_gears(
    evidence: dict[str, Any],
    *,
    current_gears: dict[int, int],
    max_gear: int = MAX_GEAR,
    n_clean_runs_for_shift: int = N_CLEAN_RUNS_FOR_SHIFT,
    n_low_runs_for_shift_down: int = N_LOW_RUNS_FOR_RECOGNITION_SHIFT_DOWN,
) -> dict[int, int]:
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
        if (
            isinstance(strong_streak, int)
            and strong_streak >= n_clean_runs_for_shift
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


def _completed_sets(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    set_size: int,
) -> list[dict[str, Any]]:
    by_set: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if (
            not isinstance(record, dict)
            or record.get("mode") != "recognition"
            or record_claimed_set_key(record) != claimed_set_key
        ):
            continue
        set_id = _record_set_id(record)
        if set_id is None:
            continue
        by_set.setdefault(set_id, []).append(record)

    completed: list[dict[str, Any]] = []
    for set_id, group in by_set.items():
        sessions = {
            session for record in group if (session := _record_set_session(record)) is not None
        }
        if len(sessions) < set_size:
            continue
        fraction = _set_fraction(group, set_size=set_size)
        if fraction is None:
            continue
        group.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
        gear = _gear_from_generation(group[0].get("generation"))
        if gear is None:
            gear = 0
        completed.append(
            {
                "set_id": set_id,
                "started_at": max(str(record.get("started_at") or "") for record in group),
                "fraction": fraction,
                "state": _recognition_state(fraction, has_evidence=True),
                "gear": gear,
            }
        )

    completed.sort(key=lambda item: item["started_at"], reverse=True)
    return completed


def _set_fraction(records: list[dict[str, Any]], *, set_size: int) -> float | None:
    fractions: list[float] = []
    analyzed_sessions: set[int] = set()
    for record in records:
        session = _record_set_session(record)
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        record_has_analysis = False
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict):
                continue
            if _exercise_has_acclimatisation_grace(exercise, exercises, session):
                record_has_analysis = True
                continue
            fraction = analysis.get("combined_fraction")
            if isinstance(fraction, (int, float)) and not isinstance(fraction, bool):
                fractions.append(float(fraction))
                record_has_analysis = True
        if record_has_analysis and session is not None:
            analyzed_sessions.add(session)
    if len(analyzed_sessions) < set_size:
        return None
    if not fractions:
        return None
    return _fraction(sum(fractions), len(fractions))


def _exercise_has_acclimatisation_grace(
    exercise: dict[str, Any],
    exercises: list[Any],
    set_session: int | None,
) -> bool:
    analysis = exercise.get("analysis")
    if not isinstance(analysis, dict):
        return False
    if analysis.get("acclimatisation_grace") is True:
        return True
    if set_session is None or set_session < 3:
        return False
    if not _exercise_index_is(exercise, 1) or _analysis_is_exact(analysis):
        return False
    second = _exercise_by_index(exercises, 2)
    if second is None:
        return False
    second_analysis = second.get("analysis")
    if not isinstance(second_analysis, dict) or not _analysis_is_exact(second_analysis):
        return False
    return _target_key(exercise) == _target_key(second)


def _exercise_by_index(exercises: list[Any], index: int) -> dict[str, Any] | None:
    for exercise in exercises:
        if isinstance(exercise, dict) and _exercise_index_is(exercise, index):
            return exercise
    return None


def _exercise_index_is(exercise: dict[str, Any], index: int) -> bool:
    value = exercise.get("index")
    return isinstance(value, int) and not isinstance(value, bool) and value == index


def _target_key(exercise: dict[str, Any]) -> str:
    target = exercise.get("target")
    return "".join(_compact_symbol_string(target)) if isinstance(target, str) else ""


def _record_set_id(record: dict[str, Any]) -> str | None:
    generation = record.get("generation")
    if not isinstance(generation, dict):
        return None
    set_id = generation.get("set_id")
    return set_id if isinstance(set_id, str) and set_id else None


def _record_set_session(record: dict[str, Any]) -> int | None:
    generation = record.get("generation")
    if not isinstance(generation, dict):
        return None
    set_session = generation.get("set_session")
    if isinstance(set_session, int) and not isinstance(set_session, bool):
        return set_session
    return None


def _gear_from_generation(generation: Any) -> int | None:
    if not isinstance(generation, dict):
        return None
    gear = generation.get("gear")
    if isinstance(gear, int) and not isinstance(gear, bool):
        return gear
    gears = _gears_from_generation(generation)
    if not gears:
        return None
    return gears[min(gears)]


def _gears_from_generation(generation: Any) -> dict[int, int]:
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


def _analysis_is_exact(analysis: dict[str, Any]) -> bool:
    fraction = analysis.get("combined_fraction")
    return isinstance(fraction, (int, float)) and not isinstance(fraction, bool) and fraction >= 1


def _recognition_state(value: float, *, has_evidence: bool) -> str:
    if not has_evidence:
        return "silent"
    if value < 0.70:
        return "low"
    if value < 0.85:
        return "building"
    if value < 0.95:
        return "steady"
    if value < 1.0:
        return "strong"
    return "exact"


def _fraction(correct: float, available: int, *, default: float = 0.0) -> float:
    if available <= 0:
        return default
    return max(0.0, min(1.0, correct / available))


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _compact_symbol_string(value: str) -> list[str]:
    return [ch.upper() for ch in value if not ch.isspace()]
