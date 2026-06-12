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
from copy_653.sequence.exercise_analysis import record_claimed_set_key
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

REVIEW_ANALYSIS_VERSION = "recognition-review-v1"
CONFUSION_TREND_SESSION_WINDOW = 20
CONFUSION_TREND_MIN_DELTA = 0.05


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


def load_recognition_confusion(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    trend_window_size: int = CONFUSION_TREND_SESSION_WINDOW,
) -> dict[str, Any]:
    """Aggregate both confusion streams across recognition sessions.

    Walks every recognition record whose claimed-set identity matches
    ``claimed_set_key`` and sums the per-exercise ``analysis`` blocks
    written at save time (layer A1). The two streams stay separate:

    * ``committed_substitutions`` — truth → what the learner committed,
      from ``substitution`` and ``caught_substitution`` slots.
    * ``caught_substitutions`` — truth → a false start they superseded
      before committing (the ``caught_*`` slots).

    A caught confusion is never folded into the committed count — that
    separation is the whole point of the windowing. Only exercises with
    ``has_evidence`` contribute; a silent exercise ("nothing heard") is
    neither right nor wrong and adds to neither stream.

    Uses all matching records (no window cap), including warm-ups —
    confusion is a slow-moving signal and warm-up utterances are real
    (matching the Koch confusion loader and the warm-up contract).
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


def _analysis_is_exact(analysis: dict[str, Any]) -> bool:
    fraction = analysis.get("combined_fraction")
    return isinstance(fraction, (int, float)) and not isinstance(fraction, bool) and fraction >= 1


def _analysis_has_miss(analysis: dict[str, Any]) -> bool:
    counts = analysis.get("counts")
    if not isinstance(counts, dict):
        return False
    value = counts.get(OUTCOME_MISS)
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


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


def _tally_pair(counter: dict[tuple[str, str], int], pair: Any) -> None:
    """Increment ``(target, typed)`` if ``pair`` is a well-formed string pair."""
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return
    target, typed = pair
    if not isinstance(target, str) or not isinstance(typed, str):
        return
    counter[(target, typed)] = counter.get((target, typed), 0) + 1


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


def _fraction(correct: int, available: int, *, default: float = 0.0) -> float:
    if available <= 0:
        return default
    return max(0.0, min(1.0, correct / available))


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default
