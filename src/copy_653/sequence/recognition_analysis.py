"""Windowing + classification for saved Symbol Recognition attempts.

Like :mod:`copy_653.sequence.exercise_analysis`, this module produces
backend evidence — not learner-facing feedback, scores, or progress
metrics (spec §9). It is the bottom layer of the recognition evidence
pipeline: it takes the raw, honest record (the played ``symbols``
schedule and the per-exercise ``voice_capture``) and reconstructs, per
played symbol, what the learner actually committed and what they said
on the way there.

The point of difference from the Koch path is timing. A typed Koch
answer is a flat string, so confusion there can only be recovered by
string alignment (:func:`exercise_analysis.load_confusion_pairs`). A
recognition attempt carries a timestamp on every utterance, which lets
us align responses to the cadence rather than to each other — and that
is what makes a *self-correction* visible. When a learner hears U,
starts to say "romeo", catches it, and lands on "uniform" in one
breath, the recogniser honestly records "romeo uniform". Flat string
alignment would treat the stray R as an insertion and discard it;
here we keep it, label it, and route it to a separate stream so a
caught confusion never counts as a committed one.

Nothing is mutated and nothing is collapsed. ``voice_capture`` stays
the verbatim record of what was said; this module only *derives* a view
over it.
"""

from __future__ import annotations

from typing import Any

from copy_653.sequence.exercise_analysis import MAX_GEAR as MAX_GEAR
from copy_653.sequence.recognition_confusion import (
    CONFUSION_TREND_MIN_DELTA as CONFUSION_TREND_MIN_DELTA,
    CONFUSION_TREND_SESSION_WINDOW as CONFUSION_TREND_SESSION_WINDOW,
    load_recognition_confusion as load_recognition_confusion,
)
from copy_653.sequence.recognition_progression import (
    GENERATION_PROFILE_VERSION as GENERATION_PROFILE_VERSION,
    N_LOW_RUNS_FOR_RECOGNITION_SHIFT_DOWN as N_LOW_RUNS_FOR_RECOGNITION_SHIFT_DOWN,
    N_LOW_SETS_FOR_RECOGNITION_SHIFT_DOWN as N_LOW_SETS_FOR_RECOGNITION_SHIFT_DOWN,
    RECOGNITION_SET_SIZE as RECOGNITION_SET_SIZE,
    build_recognition_generation_profile as build_recognition_generation_profile,
    gear_for_recognition_set as gear_for_recognition_set,
    latest_completed_set_gear_for_claimed_set as latest_completed_set_gear_for_claimed_set,
    latest_gears_for_claimed_set as latest_gears_for_claimed_set,
    load_band_evidence as load_band_evidence,
    load_set_evidence as load_set_evidence,
    resolve_gears as resolve_gears,
    resolve_set_gear as resolve_set_gear,
)
from copy_653.sequence.recognition_review import (
    REVIEW_ANALYSIS_VERSION as REVIEW_ANALYSIS_VERSION,
    attach_recognition_review_analysis as attach_recognition_review_analysis,
    recognition_review_analysis as recognition_review_analysis,
)
from copy_653.sequence.recognition_timing import (
    TIMING_TREND_MIN_DELTA_MS as TIMING_TREND_MIN_DELTA_MS,
    TIMING_TREND_SESSION_WINDOW as TIMING_TREND_SESSION_WINDOW,
    load_recognition_timing as load_recognition_timing,
)
from copy_653.sequence.recognition_windowing import (
    ANALYSIS_VERSION,
    OUTCOME_CAUGHT_CORRECT,
    OUTCOME_CAUGHT_SUBSTITUTION,
    OUTCOME_CORRECT,
    OUTCOME_MISS,
    OUTCOME_SUBSTITUTION,
    _ordered_symbols,
    window_exercise,
)


def analyse_recognition_exercises(
    exercises: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach derived answer and timing analysis blocks to each exercise.

    Pure: returns new exercise dicts with ``analysis`` merged in and the
    raw ``answer`` / ``voice_capture`` left untouched. ``symbols`` is the
    record's flat played schedule (each entry carrying an
    ``exercise_index``); it is grouped per exercise here, then each
    exercise's own ``voice_capture`` is windowed against it.

    ``analysis`` is answer-aligned and is the user-facing/progression
    signal. ``timing_analysis`` is the older onset-window reconstruction,
    retained as debugging evidence for speech lag and recogniser timing.
    """
    by_index = _symbols_by_exercise(symbols)
    updated: list[dict[str, Any]] = []
    for exercise in exercises:
        merged = dict(exercise)
        index = exercise.get("index")
        ex_symbols = by_index.get(index, []) if isinstance(index, int) else []
        capture = exercise.get("voice_capture")
        windowed = window_exercise(ex_symbols, capture if isinstance(capture, list) else [])
        merged["analysis"] = _analysis_from_answer(ex_symbols, exercise)
        merged["timing_analysis"] = _analysis_from_windowed(windowed, exercise)
        updated.append(merged)
    return updated


def apply_acclimatisation_grace(
    exercises: list[dict[str, Any]],
    *,
    set_session: int,
) -> list[dict[str, Any]]:
    """Soft-mark first-exercise misses after recognition condition changes.

    Sets 3-8 introduce the meaningful S/T difficulty ramp. The first
    exercise in those sets is the learner settling their ear into the
    changed listening condition; if the same target is repeated and then
    copied exactly, keep the honest miss but exclude it from set-level
    progression pressure.
    """
    updated = [dict(exercise) for exercise in exercises]
    if set_session < 3 or not updated:
        return updated
    first = updated[0]
    if not _exercise_index_is(first, 1):
        return updated
    first_analysis = first.get("analysis")
    if not isinstance(first_analysis, dict) or _analysis_is_exact(first_analysis):
        return updated
    second = _exercise_by_index(updated, 2)
    if second is None:
        return updated
    second_analysis = second.get("analysis")
    if not isinstance(second_analysis, dict) or not _analysis_is_exact(second_analysis):
        return updated
    if _target_key(first) != _target_key(second):
        return updated

    softened = dict(first_analysis)
    softened["acclimatisation_grace"] = True
    softened["evidence_weight"] = "soft"
    softened["progression_excluded"] = True
    first["analysis"] = softened
    updated[0] = first
    return updated


def _symbols_by_exercise(symbols: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for entry in symbols:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("exercise_index")
        if isinstance(idx, int) and not isinstance(idx, bool):
            out.setdefault(idx, []).append(entry)
    return out


def _analysis_from_windowed(windowed: dict[str, Any], exercise: dict[str, Any]) -> dict[str, Any]:
    """Build the persisted ``analysis`` block from one windowed exercise.

    Slots are stored lean — without their ``utterances``, which already
    live verbatim in ``voice_capture`` — so the record carries the
    windowing result without duplicating the raw transcript.
    """
    slots = windowed["slots"]
    counts = {
        OUTCOME_CORRECT: 0,
        OUTCOME_SUBSTITUTION: 0,
        OUTCOME_CAUGHT_CORRECT: 0,
        OUTCOME_CAUGHT_SUBSTITUTION: 0,
        OUTCOME_MISS: 0,
    }
    for slot in slots:
        counts[slot["outcome"]] += 1
    correctish = counts[OUTCOME_CORRECT] + counts[OUTCOME_CAUGHT_CORRECT]
    total = sum(counts.values())
    combined_fraction = _fraction(correctish, total)
    has_evidence = any(slot["committed"] is not None for slot in slots)
    gear = _coerce_int(exercise.get("gear"), 0)
    burden_band = _coerce_int(exercise.get("burden_band"), _coerce_int(exercise.get("index"), 0))
    lean_slots = [
        {
            "index": slot["index"],
            "truth": slot["truth"],
            "t_on": slot["t_on"],
            "tokens": slot["tokens"],
            "committed": slot["committed"],
            "superseded": slot["superseded"],
            "outcome": slot["outcome"],
        }
        for slot in slots
    ]
    return {
        "version": ANALYSIS_VERSION,
        "method": "onset-window",
        "saved": True,
        "has_evidence": has_evidence,
        "committed_answer": windowed["committed_answer"],
        "counts": counts,
        "combined_fraction": round(combined_fraction, 6),
        "recognition_state": _recognition_state(combined_fraction, has_evidence=has_evidence),
        "band_state": _recognition_state(combined_fraction, has_evidence=has_evidence),
        "burden_band": burden_band,
        "gear": gear,
        "committed_confusions": windowed["committed_confusions"],
        "caught_confusions": windowed["caught_confusions"],
        "ambiguous_lag": windowed["ambiguous_lag"],
        "slots": lean_slots,
    }


def _analysis_from_answer(
    symbols: list[dict[str, Any]],
    exercise: dict[str, Any],
) -> dict[str, Any]:
    target = _target_symbols(exercise, symbols)
    answer = _answer_symbols(exercise.get("answer"))
    counts = {
        OUTCOME_CORRECT: 0,
        OUTCOME_SUBSTITUTION: 0,
        OUTCOME_CAUGHT_CORRECT: 0,
        OUTCOME_CAUGHT_SUBSTITUTION: 0,
        OUTCOME_MISS: 0,
    }
    slots: list[dict[str, Any]] = []
    committed_confusions: list[list[str]] = []

    for index, truth in enumerate(target):
        committed = answer[index] if index < len(answer) else None
        if committed is None:
            outcome = OUTCOME_MISS
        elif committed == truth:
            outcome = OUTCOME_CORRECT
        else:
            outcome = OUTCOME_SUBSTITUTION
            committed_confusions.append([truth, committed])
        counts[outcome] += 1
        slots.append(
            {
                "index": index + 1,
                "truth": truth,
                "tokens": [committed] if committed is not None else [],
                "committed": committed,
                "superseded": [],
                "outcome": outcome,
            }
        )

    total = sum(counts.values())
    combined_fraction = _fraction(counts[OUTCOME_CORRECT], total)
    has_evidence = bool(answer)
    gear = _coerce_int(exercise.get("gear"), 0)
    burden_band = _coerce_int(exercise.get("burden_band"), _coerce_int(exercise.get("index"), 0))
    return {
        "version": ANALYSIS_VERSION,
        "method": "answer-alignment",
        "saved": True,
        "has_evidence": has_evidence,
        "committed_answer": "".join(answer),
        "counts": counts,
        "combined_fraction": round(combined_fraction, 6),
        "recognition_state": _recognition_state(combined_fraction, has_evidence=has_evidence),
        "band_state": _recognition_state(combined_fraction, has_evidence=has_evidence),
        "burden_band": burden_band,
        "gear": gear,
        "committed_confusions": committed_confusions,
        "caught_confusions": [],
        "ambiguous_lag": False,
        "slots": slots,
    }


def _target_symbols(exercise: dict[str, Any], symbols: list[dict[str, Any]]) -> list[str]:
    ordered = _ordered_symbols(symbols)
    if ordered:
        return [str(entry["symbol"]).upper() for entry in ordered]
    target = exercise.get("target")
    if not isinstance(target, str):
        return []
    return _compact_symbol_string(target)


def _answer_symbols(answer: Any) -> list[str]:
    if not isinstance(answer, str):
        return []
    return _compact_symbol_string(answer)


def _compact_symbol_string(value: str) -> list[str]:
    return [ch.upper() for ch in value if not ch.isspace()]


def _analysis_is_exact(analysis: dict[str, Any]) -> bool:
    fraction = analysis.get("combined_fraction")
    return isinstance(fraction, (int, float)) and not isinstance(fraction, bool) and fraction >= 1


def _analysis_has_miss(analysis: dict[str, Any]) -> bool:
    counts = analysis.get("counts")
    if not isinstance(counts, dict):
        return False
    value = counts.get(OUTCOME_MISS)
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


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


def _fraction(correct: int, available: int, *, default: float = 0.0) -> float:
    if available <= 0:
        return default
    return max(0.0, min(1.0, correct / available))


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default
