"""Internal analysis for saved Koch Exercise attempts.

This module deliberately produces backend evidence, not learner-facing
feedback. The values it returns are intended for records, diagnostics,
and future exercise selection. They are not scores, grades, or progress
metrics for the listening surface.
"""

from __future__ import annotations

from math import log1p
import re
from typing import Any, Callable

from copy_653.sequence.copy_exercises import _score_copy_exercise

FIXED_LISTENING_ANCHOR = "DE"
ANALYSIS_VERSION = "koch-analysis-v1"
GENERATION_PROFILE_VERSION = "koch-burden-v1"

# Default size of the recent-session window the evidence loader walks.
# The MOC recommends 5-10; 5 keeps the model responsive and avoids
# ancient evidence dominating after a learner returns from a break.
DEFAULT_EVIDENCE_WINDOW_SIZE = 5

# Threshold a per-band combined_fraction must clear to count as a
# "strong" run for gear-up purposes. Matches the band_state >= "strong"
# cutoff in :func:`_band_state`.
STRONG_FRACTION = 0.95
# Threshold below which a band run counts as "low" for gear-down. Matches
# the band_state == "low" cutoff in :func:`_band_state`.
LOW_FRACTION = 0.70

# Highest gear the candidate selector currently understands. Gears
# beyond this exist in the MOC but change generator parameters
# (max_word_length, max_words) and are a separate validation surface.
MAX_GEAR = 2
# Consecutive strong-band sessions required before a band advances one
# gear. Conservative on purpose — one lucky run should not move the
# generator, and three repeated strong runs make a chance explanation
# unlikely. The MOC suggests 2-3; 3 is the cautious end.
N_CLEAN_RUNS_FOR_SHIFT = 3
# Consecutive low-band sessions required before a band drops one gear.
# Asymmetric with N_CLEAN_RUNS_FOR_SHIFT: easier to step down than to
# step up, so the system never feels punitive.
N_LOW_RUNS_FOR_SHIFT_DOWN = 2

_SPACE_RE = re.compile(r"\s+")


def normalize_exercise_text(value: str) -> str:
    """Uppercase and collapse whitespace in an exercise or answer string."""
    return _SPACE_RE.sub(" ", value.strip().upper())


def strip_fixed_anchor(value: str) -> str:
    """Remove the fixed leading ``DE`` listening anchor if present."""
    normalized = normalize_exercise_text(value)
    if normalized == FIXED_LISTENING_ANCHOR:
        return ""
    prefix = f"{FIXED_LISTENING_ANCHOR} "
    if normalized.startswith(prefix):
        return normalized[len(prefix) :].strip()
    return normalized


def burden_score_for_exercise(played: str) -> int:
    """Return the abstract burden score for ``played`` excluding ``DE``."""
    core = strip_fixed_anchor(played)
    return _score_copy_exercise(core) if core else 0


def build_generation_profile(
    *,
    claimed_set: tuple[str, ...],
    candidate_count: int,
    exercise_count: int,
    gears: list[int] | None = None,
) -> dict[str, Any]:
    """Build the generation metadata persisted with a Koch record."""
    resolved_gears = gears if gears is not None else [0] * exercise_count
    return {
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


def build_exercise_entries(
    exercises: list[str],
    *,
    scores: list[int] | tuple[int, ...],
    gears: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Build persisted per-exercise records before answers are saved."""
    resolved_gears = gears if gears is not None else [0] * len(exercises)
    entries: list[dict[str, Any]] = []
    for idx, played in enumerate(exercises):
        burden_score = scores[idx] if idx < len(scores) else burden_score_for_exercise(played)
        entries.append(
            {
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
        )
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


def spacing_weight_for_claimed_set(claimed_set_size: int) -> float:
    """Spacing weight in [0.15, 0.5] decreasing with claimed-set size.

    At small claimed sets symbol Levenshtein has few candidates to
    discriminate (K vs M is the only confusion at size 2), so word-
    boundary detection carries most of the listening evidence. As the
    set grows, symbol misses become more diagnostic and spacing
    proportionally less so.
    """
    if claimed_set_size <= 0:
        return 0.5
    return max(0.15, min(0.5, 1.0 / claimed_set_size))


def analyse_answer(
    *,
    played: str,
    answer: str,
    exercise_index: int,
    burden_score: int,
    burden_band: int,
    gear: int,
    claimed_set_size: int,
    repeat_weight: float = 1.0,
) -> dict[str, Any]:
    """Compare one saved answer to one played exercise.

    Symbol evidence ignores spaces first so a missed or added space does
    not poison the whole line. Spacing evidence is tracked separately
    and weighted relative to claimed-set size — see
    :func:`spacing_weight_for_claimed_set`.
    """
    core = strip_fixed_anchor(played)
    answer_core = strip_fixed_anchor(answer)
    symbol_truth = _symbols_only(core)
    symbol_answer = _symbols_only(answer_core)
    symbol_available = max(len(symbol_truth), len(symbol_answer))
    symbol_distance = _levenshtein(symbol_truth, symbol_answer)
    symbol_correct = max(0, symbol_available - symbol_distance)

    truth_boundaries = _word_boundaries(core)
    answer_boundaries = _word_boundaries(answer_core)
    spacing_available = max(len(truth_boundaries), len(answer_boundaries))
    spacing_correct = len(truth_boundaries & answer_boundaries)

    symbol_fraction = _fraction(symbol_correct, symbol_available)
    spacing_weight = spacing_weight_for_claimed_set(claimed_set_size)
    if spacing_available > 0:
        spacing_fraction = _fraction(spacing_correct, spacing_available)
        combined = ((1.0 - spacing_weight) * symbol_fraction) + (spacing_weight * spacing_fraction)
    else:
        # Single-word exercise — no boundary evidence to combine. Crediting a
        # phantom 1.0 here would inflate the score for free; the spec demands
        # an honest scalar so we use symbol evidence alone.
        spacing_fraction = 1.0
        combined = symbol_fraction
    bounded_repeat_weight = min(1.0, max(0.0, repeat_weight))
    burden_weight = 1.0 + log1p(max(0, burden_score))
    position_weight = 1.0 + ((max(1, exercise_index) - 1) * 0.10)
    evidence = combined * burden_weight * position_weight * bounded_repeat_weight

    return {
        "version": ANALYSIS_VERSION,
        "saved": True,
        "normalized_answer": normalize_exercise_text(answer),
        "answer_core": answer_core,
        "symbol_correct_units": symbol_correct,
        "symbol_available_units": symbol_available,
        "symbol_edit_distance": symbol_distance,
        "spacing_correct_units": spacing_correct,
        "spacing_available_units": spacing_available,
        "spacing_weight": round(spacing_weight, 3),
        "claimed_set_size": claimed_set_size,
        "repeat_weight": round(bounded_repeat_weight, 3),
        "combined_fraction": round(combined, 6),
        "evidence": round(evidence, 6),
        "band_state": _band_state(combined),
        "burden_band": burden_band,
        "gear": gear,
    }


def _symbols_only(value: str) -> str:
    return normalize_exercise_text(value).replace(" ", "")


def _word_boundaries(value: str) -> set[int]:
    words = [word for word in normalize_exercise_text(value).split(" ") if word]
    boundaries: set[int] = set()
    cursor = 0
    for word in words[:-1]:
        cursor += len(word)
        boundaries.add(cursor)
    return boundaries


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, lch in enumerate(left, start=1):
        current = [i]
        for j, rch in enumerate(right, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (0 if lch == rch else 1)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def _fraction(correct: int, available: int, *, default: float = 0.0) -> float:
    if available <= 0:
        return default
    return max(0.0, min(1.0, correct / available))


def _band_state(value: float) -> str:
    if value < 0.70:
        return "low"
    if value < 0.85:
        return "building"
    if value < 0.95:
        return "steady"
    if value < 1.0:
        return "strong"
    return "exact"


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _repeat_weight(occurrence: int) -> float:
    if occurrence <= 1:
        return 1.0
    if occurrence == 2:
        return 0.7
    if occurrence == 3:
        return 0.5
    return 0.35


def record_claimed_set_key(record: dict[str, Any]) -> str:
    """Return the claimed-set identity for a saved koch-exercise record.

    Prefers ``generation.claimed_set_key`` (schema 2.0+); falls back to
    sorting ``claimed_set`` for legacy schema 1.3 records that pre-date
    the persisted key. Returns ``""`` when neither is present so a
    malformed file does not crash the loader.
    """
    generation = record.get("generation")
    if isinstance(generation, dict):
        stored = generation.get("claimed_set_key")
        if isinstance(stored, str):
            return stored
    claimed = record.get("claimed_set")
    if isinstance(claimed, list):
        return " ".join(sorted(str(s) for s in claimed))
    return ""


def load_band_evidence(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_EVIDENCE_WINDOW_SIZE,
) -> dict[str, Any]:
    """Aggregate per-band evidence over recent sessions for one claimed set.

    ``records`` is the list of already-loaded koch-exercise record dicts
    — the caller does the disk walk so this helper stays pure. Only
    records whose claimed-set identity matches ``claimed_set_key``
    contribute. The matching set is sorted by ``started_at`` descending
    and truncated to ``window_size`` before aggregation.

    For each burden band observed in the window, the helper records the
    most-recent-first list of ``combined_fraction`` values along with
    streaks of consecutive strong (>= 0.95) and low (< 0.70) runs from
    the most recent observation. Streaks are the input the gear-up /
    gear-down rule consumes; the raw fraction list is what the
    diagnostic panel renders.

    Sessions with no saved-answer analysis contribute nothing — an
    unanswered session is exposure, not evidence.
    """
    matching: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("mode") != "koch-exercise":
            continue
        if record_claimed_set_key(record) != claimed_set_key:
            continue
        matching.append(record)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    window = matching[: max(0, window_size)]

    band_entries: dict[int, list[tuple[float, str]]] = {}
    for session in window:
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
            band_entries.setdefault(burden_band, []).append(
                (float(fraction), str(state) if isinstance(state, str) else "")
            )

    bands: list[dict[str, Any]] = []
    for band_index in sorted(band_entries):
        entries = band_entries[band_index]
        fractions = [f for f, _ in entries]
        states = [s for _, s in entries]
        bands.append(
            {
                "burden_band": band_index,
                "recent_fractions": [round(f, 6) for f in fractions],
                "recent_band_states": states,
                "strong_streak": _streak(fractions, lambda v: v >= STRONG_FRACTION),
                "low_streak": _streak(fractions, lambda v: v < LOW_FRACTION),
            }
        )

    return {
        "claimed_set_key": claimed_set_key,
        "session_count": len(matching),
        "window_size": window_size,
        "sessions_used": len(window),
        "bands": bands,
    }


def _streak(values: list[float], predicate: Callable[[float], bool]) -> int:
    count = 0
    for value in values:
        if not predicate(value):
            return count
        count += 1
    return count


def latest_gears_for_claimed_set(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
) -> dict[int, int]:
    """Return the per-band gears from the most recent matching session.

    Looks at all records — saved or not — because the gear a session
    ran at is locked in at generation time regardless of whether the
    learner later saved answers. A session that produced no answer
    evidence still establishes the gear floor the next session inherits.

    Returns ``{}`` when no record matches; the resolver treats missing
    bands as gear 0.
    """
    matching = [
        r
        for r in records
        if isinstance(r, dict)
        and r.get("mode") == "koch-exercise"
        and record_claimed_set_key(r) == claimed_set_key
    ]
    if not matching:
        return {}
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    latest = matching[0]
    generation = latest.get("generation")
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
        if isinstance(idx, int) and not isinstance(idx, bool):
            if isinstance(gear, int) and not isinstance(gear, bool):
                out[idx] = gear
    return out


def resolve_gears(
    evidence: dict[str, Any],
    *,
    current_gears: dict[int, int],
    max_gear: int = MAX_GEAR,
    n_clean_runs_for_shift: int = N_CLEAN_RUNS_FOR_SHIFT,
    n_low_runs_for_shift_down: int = N_LOW_RUNS_FOR_SHIFT_DOWN,
) -> dict[int, int]:
    """Compute per-band gear assignments for the next session.

    Step changes by one per call: a band that has met the strong-streak
    threshold advances one gear, a band that has met the low-streak
    threshold drops one gear, otherwise the gear is held. Bands not
    represented in ``evidence`` keep whatever gear was in
    ``current_gears``.

    The single-step constraint is intentional — even a long strong
    streak only adds one gear per session, so any move-up is followed
    by another session of evidence at the new gear before another
    advance is possible.
    """
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
