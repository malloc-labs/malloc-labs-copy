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
    """Attach a derived ``analysis`` block to each recognition exercise.

    Pure: returns new exercise dicts with ``analysis`` merged in and the
    raw ``answer`` / ``voice_capture`` left untouched. ``symbols`` is the
    record's flat played schedule (each entry carrying an
    ``exercise_index``); it is grouped per exercise here, then each
    exercise's own ``voice_capture`` is windowed against it.

    The committed answer in the analysis is *voice-derived* — the last
    token per cadence window — and may differ from the exercise's
    ``answer`` field, which the learner can edit after the session. That
    divergence is deliberate: the analysis reflects what was *heard*
    (and is where a self-correction is visible), while ``answer`` is the
    learner's reviewed commit. Storing both keeps "Vosk got it wrong"
    distinguishable from "the learner said the wrong thing".

    Recognition is not geared, so no weighted evidence scalar is
    produced — only the windowed classification, outcome counts, and the
    two confusion streams. A future gearing model derives whatever
    fraction it needs from the counts already persisted here.
    """
    by_index = _symbols_by_exercise(symbols)
    updated: list[dict[str, Any]] = []
    for exercise in exercises:
        merged = dict(exercise)
        index = exercise.get("index")
        ex_symbols = by_index.get(index, []) if isinstance(index, int) else []
        capture = exercise.get("voice_capture")
        windowed = window_exercise(ex_symbols, capture if isinstance(capture, list) else [])
        merged["analysis"] = _analysis_from_windowed(windowed, exercise)
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


def build_recognition_generation_profile(
    *,
    claimed_set: tuple[str, ...],
    exercise_count: int,
    gears: list[int] | None = None,
) -> dict[str, Any]:
    """Build Recognition generation metadata with per-slot gears."""
    resolved_gears = gears if gears is not None else [0] * exercise_count
    return {
        "profile_version": GENERATION_PROFILE_VERSION,
        "claimed_set_key": " ".join(sorted(claimed_set)),
        "exercise_count": exercise_count,
        "bands": [
            {
                "index": idx + 1,
                "gear": resolved_gears[idx] if idx < len(resolved_gears) else 0,
            }
            for idx in range(exercise_count)
        ],
    }


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
            if not isinstance(analysis, dict) or analysis.get("has_evidence") is not True:
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
    committed: dict[tuple[str, str], int] = {}
    caught: dict[tuple[str, str], int] = {}
    exercises_used = 0

    for record in records:
        if not isinstance(record, dict) or record.get("mode") != "recognition":
            continue
        if record_claimed_set_key(record) != claimed_set_key:
            continue
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
            for pair in analysis.get("committed_confusions") or []:
                _tally_pair(committed, pair)
            for pair in analysis.get("caught_confusions") or []:
                _tally_pair(caught, pair)

    return {
        "claimed_set_key": claimed_set_key,
        "exercises_used": exercises_used,
        "committed_substitutions": _sorted_pairs(committed),
        "caught_substitutions": _sorted_pairs(caught),
    }


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
