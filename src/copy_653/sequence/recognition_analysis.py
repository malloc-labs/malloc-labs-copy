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

ANALYSIS_VERSION = "recognition-analysis-v1"
GENERATION_PROFILE_VERSION = "recognition-progression-v1"
RECOGNITION_SET_SIZE = 8
CONFUSION_TREND_SESSION_WINDOW = 5
CONFUSION_TREND_MIN_DELTA = 0.05

# Per-slot outcome labels. ``caught_*`` outcomes carry one or more
# superseded tokens — a false start the learner spoke before committing.
OUTCOME_CORRECT = "correct"
OUTCOME_SUBSTITUTION = "substitution"
OUTCOME_CAUGHT_CORRECT = "caught_correct"
OUTCOME_CAUGHT_SUBSTITUTION = "caught_substitution"
OUTCOME_MISS = "miss"

N_LOW_RUNS_FOR_RECOGNITION_SHIFT_DOWN = N_LOW_RUNS_FOR_SHIFT_DOWN


def window_exercise(
    symbols: list[dict[str, Any]],
    voice_capture: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reconstruct per-symbol responses for one recognition exercise.

    ``symbols`` is the played truth schedule for a single exercise —
    each entry an ``{"symbol", "t_on", ...}`` dict, in play order.
    ``voice_capture`` is that exercise's list of recogniser finals —
    each an ``{"text", "symbols", "t"}`` dict, where ``symbols`` is the
    already-tokenised list and ``t`` is seconds since session start.

    Each utterance is attached to the *latest symbol already played* —
    the last symbol whose ``t_on`` is at or before the utterance time.
    With the ``say_after`` flow a response always lands in the window
    that opens when its symbol plays and closes when the next one does;
    the final symbol's window runs to the end. Utterances that arrive
    before the first symbol plays cannot be a response to anything and
    are surfaced in ``pre_symbol`` rather than forced onto slot 1.

    Within a window the tokens are taken in chronological order; the
    last token is what the learner *committed*, everything before it is
    *superseded*. The committed tokens, joined, are the answer that a
    fraction/evidence layer should align against truth — corrections
    no longer inflate its length.

    The returned dict carries, per exercise: ``committed_answer``, the
    two confusion streams (``committed_confusions`` and
    ``caught_confusions``, never merged), an ``ambiguous_lag`` flag (set
    when an empty window and a multi-token window coexist, i.e. the
    learner may have fallen behind rather than self-corrected — the
    per-slot labels are unreliable in that case and the next layer
    should treat them with care), ``pre_symbol``, and the per-symbol
    ``slots``.
    """
    ordered = _ordered_symbols(symbols)
    onsets = [float(entry["t_on"]) for entry in ordered]

    # Bucket utterances by the latest symbol whose t_on <= t. Index -1
    # is the pre-symbol bucket (arrived before anything played). Gear 2+
    # records may play a whole word/pair before the recognition window;
    # when a multi-token utterance lands after the final symbol in that
    # word, distribute those tokens across the word slots instead of
    # forcing them all onto the final symbol.
    buckets: dict[int, list[dict[str, Any]]] = {}
    pre_symbol: list[dict[str, Any]] = []
    for utterance in voice_capture:
        t = _utterance_time(utterance)
        slot = _latest_played_index(onsets, t)
        if slot < 0:
            pre_symbol.append(utterance)
        else:
            tokens = _utterance_symbols(utterance)
            distributed = _distribute_word_utterance(ordered, slot, utterance, tokens)
            if distributed:
                for target_slot, token in distributed:
                    split = dict(utterance)
                    split["symbols"] = [token]
                    buckets.setdefault(target_slot, []).append(split)
            else:
                buckets.setdefault(slot, []).append(utterance)

    slots: list[dict[str, Any]] = []
    committed_tokens: list[str] = []
    committed_confusions: list[list[str]] = []
    caught_confusions: list[list[str]] = []
    saw_miss = False
    saw_multi_token = False

    for index, entry in enumerate(ordered):
        truth = str(entry["symbol"])
        t_on = float(entry["t_on"])
        utterances = buckets.get(index, [])
        utterances.sort(key=_utterance_time)
        tokens = [tok for utterance in utterances for tok in _utterance_symbols(utterance)]

        committed = tokens[-1] if tokens else None
        superseded = tokens[:-1]

        if committed is not None:
            committed_tokens.append(committed)
        if len(tokens) > 1:
            saw_multi_token = True

        outcome = _classify(truth, committed, superseded)
        if outcome == OUTCOME_MISS:
            saw_miss = True

        if committed is not None and committed != truth:
            committed_confusions.append([truth, committed])
        for token in superseded:
            if token != truth:
                caught_confusions.append([truth, token])

        slots.append(
            {
                "index": index + 1,
                "truth": truth,
                "t_on": t_on,
                "tokens": tokens,
                "committed": committed,
                "superseded": superseded,
                "outcome": outcome,
                "utterances": utterances,
            }
        )

    return {
        "version": ANALYSIS_VERSION,
        "committed_answer": "".join(committed_tokens),
        "committed_confusions": committed_confusions,
        "caught_confusions": caught_confusions,
        "ambiguous_lag": saw_miss and saw_multi_token,
        "pre_symbol": pre_symbol,
        "slots": slots,
    }


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
    n_low_sets_for_shift_down: int = 1,
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
            analysis = exercise.get("analysis")
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


def _tally_pair(counter: dict[tuple[str, str], int], pair: Any) -> None:
    """Increment ``(target, typed)`` if ``pair`` is a well-formed string pair."""
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return
    target, typed = pair
    if not isinstance(target, str) or not isinstance(typed, str):
        return
    counter[(target, typed)] = counter.get((target, typed), 0) + 1


def _sorted_pairs(counter: dict[tuple[str, str], int]) -> list[dict[str, Any]]:
    return sorted(
        [{"target": t, "typed": a, "count": c} for (t, a), c in counter.items()],
        key=lambda p: (-p["count"], p["target"], p["typed"]),
    )


def _classify(truth: str, committed: str | None, superseded: list[str]) -> str:
    if committed is None:
        return OUTCOME_MISS
    if superseded:
        return OUTCOME_CAUGHT_CORRECT if committed == truth else OUTCOME_CAUGHT_SUBSTITUTION
    return OUTCOME_CORRECT if committed == truth else OUTCOME_SUBSTITUTION


def _fraction(correct: int, available: int, *, default: float = 0.0) -> float:
    if available <= 0:
        return default
    return max(0.0, min(1.0, correct / available))


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _distribute_word_utterance(
    ordered: list[dict[str, Any]],
    latest_slot: int,
    utterance: dict[str, Any],
    tokens: list[str],
) -> list[tuple[int, str]]:
    if len(tokens) <= 1:
        return []
    if latest_slot < 0 or latest_slot >= len(ordered):
        return []
    latest = ordered[latest_slot]
    word = latest.get("word")
    word_index = latest.get("word_index")
    if not isinstance(word, str) or len(word) <= 1:
        return []
    if not isinstance(word_index, int) or isinstance(word_index, bool):
        return []
    exercise_index = latest.get("exercise_index")
    word_slots = [
        idx
        for idx, entry in enumerate(ordered)
        if entry.get("exercise_index") == exercise_index
        and entry.get("word_index") == word_index
        and entry.get("word") == word
    ]
    if not word_slots or latest_slot != word_slots[-1]:
        return []
    if len(tokens) > len(word_slots):
        return []
    return list(zip(word_slots[: len(tokens)], tokens, strict=False))


def _ordered_symbols(symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ``[(symbol, t_on), ...]`` sorted by onset.

    Entries without a usable symbol or numeric ``t_on`` are skipped — a
    malformed schedule should not crash the loader (spec §1.5 is about
    config; here a defensive skip keeps derived evidence honest).
    """
    out: list[dict[str, Any]] = []
    for entry in symbols:
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("symbol")
        t_on = entry.get("t_on")
        if not isinstance(symbol, str) or not symbol:
            continue
        if not _is_number(t_on):
            continue
        clean = dict(entry)
        clean["symbol"] = symbol
        clean["t_on"] = float(t_on)
        out.append(clean)
    out.sort(key=lambda item: float(item["t_on"]))
    return out


def _latest_played_index(onsets: list[float], t: float) -> int:
    """Index of the last onset that is <= ``t``; -1 if ``t`` precedes all."""
    slot = -1
    for index, onset in enumerate(onsets):
        if onset <= t:
            slot = index
        else:
            break
    return slot


def _utterance_time(utterance: dict[str, Any]) -> float:
    t = utterance.get("t") if isinstance(utterance, dict) else None
    return float(t) if _is_number(t) else 0.0


def _utterance_symbols(utterance: dict[str, Any]) -> list[str]:
    if not isinstance(utterance, dict):
        return []
    raw = utterance.get("symbols")
    if not isinstance(raw, list):
        return []
    return [tok for tok in raw if isinstance(tok, str) and tok]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
