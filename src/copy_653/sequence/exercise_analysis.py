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

# Highest band gear in the curriculum. Gears 0–2 escalate *content*
# (which slice of the burden pool a slot draws from); gear 3 is
# content-equivalent to gear 2 (already at the band ceiling) and
# instead engages session-level scaffold-break audio — randomised DE
# lead-ins and a dynamic noise floor — to disrupt the structural cues
# the learner has built up over focused listening. Originally
# scaffold-break lived on its own boolean wire; we folded it into the
# gear axis so "the learner reaches a capability, the next gear kicks
# in" stays a single story instead of bifurcating axes.
MAX_GEAR = 3
# Highest *content*-changing gear. Beyond this, gears layer audio /
# assembly disruption on top of gear 2's content; the slot range stays
# the same. Used by ``copy_exercises._slot_range`` to know when to
# fall through.
MAX_CONTENT_GEAR = 2
# Consecutive strong-band sessions required before a band advances one
# gear. Conservative on purpose — one lucky run should not move the
# generator, and three repeated strong runs make a chance explanation
# unlikely. The MOC suggests 2-3; 3 is the cautious end.
N_CLEAN_RUNS_FOR_SHIFT = 3
# Consecutive low-band sessions required before a band drops one gear.
# Inverted asymmetry with N_CLEAN_RUNS_FOR_SHIFT (3 to climb, 4 to
# retreat): once a band has earned its current gear we trust it longer
# than the climb required, because the higher gears layer audio
# disruption on top of the content (scaffold-break at MAX_GEAR, RST
# windows within it) and an isolated sub-0.70 run is an expected
# outcome of that disruption rather than evidence the learner regressed.
# The RST sub-axis carries its own, faster-reacting threshold
# (N_LOW_RUNS_FOR_RST_STEP_DOWN) so within-gear-3 windows can still
# slide back to give traction.
N_LOW_RUNS_FOR_SHIFT_DOWN = 4
# Consecutive low-band runs required before an RST window step slides
# back one notch (toward an easier S/T window). Kept at 2 so the
# within-gear-3 sub-axis can still accommodate quickly even while the
# band itself sits at gear 3 for longer — the band-gear axis and the
# RST sub-axis are intentionally on different reaction timescales.
N_LOW_RUNS_FOR_RST_STEP_DOWN = 2

# Per-band RST sub-axis at gear MAX_GEAR. Steps 0..MAX_RST_STEP each
# anchor a 3-wide window on the RST 1-9 scale; step 0 is (7..9) and
# every subsequent step slides one notch toward the harsher end so
# step 5 is (2..4). S and T axes progress independently using the same
# strong/low/single-step machinery as the gear axis; per-axis evidence
# is gated on the per-exercise draw landing at the window bottom of
# its current step (see :func:`is_eligible_for_axis`), so each axis
# only advances on sessions that actually stressed it.
MAX_RST_STEP = 5
RST_WINDOW_WIDTH = 3
RST_WINDOW_TOP = 9

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
            if not isinstance(analysis, dict) or analysis.get("saved") is not True:
                continue
            burden_band = exercise.get("burden_band")
            if not isinstance(burden_band, int) or isinstance(burden_band, bool):
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            state = analysis.get("band_state")
            gear = session_gears.get(burden_band)
            if gear is None:
                raw_gear = exercise.get("gear", 0)
                gear = (
                    raw_gear if isinstance(raw_gear, int) and not isinstance(raw_gear, bool) else 0
                )
            band_entries.setdefault(burden_band, []).append(
                (
                    float(fraction),
                    str(state) if isinstance(state, str) else "",
                    gear,
                )
            )

    bands: list[dict[str, Any]] = []
    for band_index in sorted(band_entries):
        entries = band_entries[band_index]
        fractions = [f for f, _, _ in entries]
        states = [s for _, s, _ in entries]
        bands.append(
            {
                "burden_band": band_index,
                "recent_fractions": [round(f, 6) for f in fractions],
                "recent_band_states": states,
                "strong_streak": _streak_at_current_gear(entries, lambda v: v >= STRONG_FRACTION),
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


def _streak(values: list[float], predicate: Callable[[float], bool]) -> int:
    count = 0
    for value in values:
        if not predicate(value):
            return count
        count += 1
    return count


def _streak_at_current_gear(
    entries: list[tuple[float, str, int]],
    predicate: Callable[[float], bool],
) -> int:
    """Streak of consecutive entries that match ``predicate`` AND share
    the gear of the most recent entry.

    A gear shift breaks the streak — the new gear has to earn its own
    streak from scratch. This makes "three strong runs" mean three
    strong runs *at the gear the band is currently running*, so the
    next advance reflects sustained performance at the new difficulty
    rather than counting prior easier runs.
    """
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


def _gears_from_generation(generation: Any) -> dict[int, int]:
    """Extract ``{index: gear}`` from a generation profile dict.

    Defensive against shape drift — anything that does not match the
    expected ``{"bands": [{"index": int, "gear": int}, ...]}`` shape
    is silently skipped.
    """
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
    return _gears_from_generation(matching[0].get("generation"))


def load_band_history(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
) -> dict[str, Any]:
    """Chronological per-band history for one claimed-set key.

    Unlike :func:`load_band_evidence`, this returns the *complete*
    matching history (no window cap) and reports gear-change events so
    a lifetime view can show how each band's gear has evolved. Sessions
    that pre-date ``generation.run_index`` get a chronological fallback
    index so legacy records still render.

    Returns
    -------
    A dict with:

    * ``claimed_set_key`` — echoed back.
    * ``session_count`` — number of matching records.
    * ``sessions`` — chronological list of ``{run_index, started_at}``.
    * ``bands`` — sorted list of ``{burden_band, entries}`` where
      ``entries`` carries ``run_index``, ``started_at``, ``fraction``
      (``None`` when the session had no saved analysis for this band),
      ``gear`` (the gear that session ran the band at), and
      ``band_state``.
    * ``gear_changes`` — chronological list of ``{burden_band,
      run_index, started_at, previous_gear, current_gear}`` events.
    * ``current_gears`` — ``{index: gear}`` from the most recent
      session's generation profile.
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

            gear = session_gears.get(burden_band)
            if gear is None:
                raw_gear = exercise.get("gear", 0)
                gear = (
                    raw_gear if isinstance(raw_gear, int) and not isinstance(raw_gear, bool) else 0
                )

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
    """Whether the learner is ready for the next-symbol suggestion.

    Returns ``True`` when, for the given ``claimed_set_key``:

    * every burden band's current gear is at ``max_gear``, and
    * each band has at least ``n_strong_required`` recent sessions with
      ``combined_fraction >= strong_fraction`` in a ``window_size``-deep
      window, and
    * each band's most-recent recorded fraction is also
      ``>= strong_fraction``.

    Gear-agnostic for the "strong in window" and "latest strong" checks
    on purpose — adding a new symbol does not strand existing ones
    (philosophy §3.7), so prior strong runs at lower gears stay
    informative. The gear-ceiling check is separate and uses the
    most-recent session's generator profile (via
    :func:`latest_gears_for_claimed_set`), which is the authoritative
    "where this band currently runs."

    Returns ``False`` on insufficient evidence (empty records, an empty
    ``claimed_set_key``, no band data) rather than raising — the call
    site only needs a boolean and "no nudge" is the safe default.
    """
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


def rst_window_for_step(step: int) -> tuple[int, int]:
    """Return the inclusive (lo, hi) RST draw window for a sub-axis step.

    Steps outside ``[0, MAX_RST_STEP]`` are clamped so callers can pass
    raw values without pre-checking.
    """
    clamped = max(0, min(MAX_RST_STEP, int(step)))
    hi = RST_WINDOW_TOP - clamped
    lo = hi - RST_WINDOW_WIDTH + 1
    return lo, hi


def is_eligible_for_axis(drawn: int, step: int) -> bool:
    """Whether a drawn S or T value sits at the bottom of its step's window.

    Bottom-of-window is the routing rule that keeps the S and T sub-axes
    genuinely independent: an exercise contributes to an axis's evidence
    only when its draw landed at the harshest single value in the
    current 3-wide window, so each axis only advances on sessions that
    actually stressed it.
    """
    lo, _ = rst_window_for_step(step)
    return int(drawn) == lo


def _rst_steps_from_generation(generation: Any) -> dict[int, tuple[int, int]]:
    """Extract ``{burden_band: (s_step, t_step)}`` from a generation profile.

    Defensive against shape drift — non-conforming entries are silently
    skipped. Pre-schema-2.1 sessions carry no ``rst_steps`` block; the
    resolver treats absent bands as step ``(0, 0)``.
    """
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
    """Per-band ``(s_step, t_step)`` from the most recent matching session.

    Returns ``{}`` when no record matches or the most recent record has
    no ``rst_steps`` block. A band that has dropped out of gear
    ``MAX_GEAR`` between sessions will not appear in the most recent
    record's ``rst_steps`` and is therefore reset to ``(0, 0)`` if it
    climbs back — matching the philosophy of a clean re-entry rather
    than a buried prior state.
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
    """Streak of newest-first entries matching ``predicate`` at the current step.

    A step change breaks the streak so the new step has to earn its own
    evidence — mirrors :func:`_streak_at_current_gear`.
    """
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
    """Per-band per-axis evidence at gear ``MAX_GEAR`` for the RST sub-axis.

    For each session matching ``claimed_set_key`` (newest first) and
    each band at gear ``MAX_GEAR``, considers the band's exercise only
    when its drawn ``s`` / ``t`` was at the bottom of the then-current
    step's window. The first ``window_size`` eligible entries per
    (band, axis) become that axis's recent evidence; strong / low
    streaks are counted consecutively from newest while the step is
    held constant.

    Pre-schema-2.1 sessions (no ``generation.rst_steps`` and no per-
    exercise ``s`` / ``t``) contribute nothing — RST evidence restarts
    cleanly when the new pipeline ships.
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
            gear = session_gears.get(burden_band)
            if gear is None:
                raw_gear = exercise.get("gear", 0)
                gear = (
                    raw_gear if isinstance(raw_gear, int) and not isinstance(raw_gear, bool) else 0
                )
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
    """Per-band ``(s_step, t_step)`` for the next session.

    Mirrors :func:`resolve_gears`: single-step ±1 per axis per call,
    clamped to ``[0, max_step]``, evidence-driven via the same strong /
    low streak thresholds. Bands not represented in ``axis_evidence``
    keep whatever step pair was in ``current_steps``.
    """
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
