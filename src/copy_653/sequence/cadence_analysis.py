"""Internal analysis for finalized Cadence send sessions.

Like Koch analysis, this module produces backend evidence for record
diagnostics and future exercise selection. It is not learner-facing
feedback and it is only applied when a cadence session is finalized.
"""

from __future__ import annotations

from math import log1p
from typing import Any

from copy_653.audio import timing
from copy_653.sequence.copy_exercises import _score_copy_exercise
from copy_653.sequence.exercise_analysis import (
    LOW_FRACTION,
    MAX_GEAR,
    N_CLEAN_RUNS_FOR_SHIFT,
    STRONG_FRACTION,
    _levenshtein,
    _streak_at_current_gear,
)

ANALYSIS_VERSION = "cadence-analysis-v1"
GENERATION_PROFILE_VERSION = "cadence-burden-v1"
DEFAULT_EVIDENCE_WINDOW_SIZE = 5

# Consecutive low-band sessions required before a band drops one gear
# in cadence-send. Asymmetric with N_CLEAN_RUNS_FOR_SHIFT (3 to climb,
# 2 to retreat): easier to step down than to step up, so the system
# never feels punitive. Held separately from the koch threshold (which
# is inverted to 4 because koch's higher gears layer audio disruption
# the cadence axis does not have) so each mode's down-trigger can move
# independently as the curricula evolve.
N_LOW_RUNS_FOR_SHIFT_DOWN = 2


def build_cadence_generation_profile(
    *,
    claimed_set: tuple[str, ...],
    candidate_count: int,
    exercise_count: int,
    gears: list[int] | None = None,
) -> dict[str, Any]:
    """Build generation metadata persisted with a cadence-send record."""
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


def build_cadence_exercise_entries(
    exercises: list[str],
    *,
    scores: list[int] | tuple[int, ...],
    gears: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Build persisted cadence exercise entries before final analysis."""
    resolved_gears = gears if gears is not None else [0] * len(exercises)
    entries: list[dict[str, Any]] = []
    for idx, target in enumerate(exercises):
        entries.append(
            {
                "index": idx + 1,
                "target": target,
                "burden_score": scores[idx] if idx < len(scores) else _score_copy_exercise(target),
                "burden_band": idx + 1,
                "gear": resolved_gears[idx] if idx < len(resolved_gears) else 0,
                "attempts": [],
                "analysis": {
                    "version": ANALYSIS_VERSION,
                    "saved": False,
                },
            }
        )
    return entries


def apply_copy_key_analysis(
    entries: list[dict[str, Any]],
    *,
    sent: list[dict[str, Any]],
    key_events: list[dict[str, Any]],
    character_wpm: int,
) -> list[dict[str, Any]]:
    """Return copy-key exercise entries with finalized attempts/analysis.

    Copy-key sent streams use BK (B followed by K) prosign boundaries
    to delimit exercises, unlike cadence-send which walks targets
    sequentially. This function splits the stream by those boundaries,
    then analyses each bucket independently using the same per-attempt
    helpers as cadence analysis.
    """
    normalised = [_normalise_sent_event(event) for event in sent]
    dit_seconds = timing.dit_seconds(character_wpm)
    buckets = _split_sent_by_bk_boundary(normalised)
    updated: list[dict[str, Any]] = []

    for idx, raw_entry in enumerate(entries):
        entry = dict(raw_entry)
        target = str(entry.get("target", ""))
        bucket = buckets[idx] if idx < len(buckets) else []
        attempts = _segment_attempts(target, bucket)
        analysed_attempts = [
            _analyse_attempt(
                target, attempt, key_events=key_events, dit_seconds=dit_seconds, mode="copy-key"
            )
            for attempt in attempts
        ]
        selected_index = _select_attempt_index(analysed_attempts)
        selected = analysed_attempts[selected_index] if selected_index is not None else None

        entry["attempts"] = analysed_attempts
        entry["analysis"] = _build_exercise_analysis(
            entry,
            selected,
            attempt_count=len(analysed_attempts),
            selected_attempt_index=selected_index,
        )
        updated.append(entry)

    return updated


def _split_sent_by_bk_boundary(
    sent: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Split a flat sent stream into per-exercise buckets by BK boundaries.

    Copy-key sessions delimit exercise boundaries with a BK prosign
    (B immediately followed by K). The B and K events themselves are
    stripped — they are protocol, not learner keying.
    """
    buckets: list[list[dict[str, Any]]] = [[]]
    for i, event in enumerate(sent):
        symbol = event.get("symbol", "")
        if symbol == "K" and i > 0 and sent[i - 1].get("symbol") == "B":
            bucket = buckets[-1]
            if bucket and bucket[-1].get("symbol") == "B":
                bucket.pop()
            buckets.append([])
            continue
        buckets[-1].append(event)
    return buckets


def apply_cadence_analysis(
    entries: list[dict[str, Any]],
    *,
    sent: list[dict[str, Any]],
    key_events: list[dict[str, Any]],
    character_wpm: int,
) -> list[dict[str, Any]]:
    """Return cadence exercise entries with finalized attempts/analysis.

    The sent stream is walked once across the target list. A target is
    advanced only after a complete matching attempt, so the next
    exercise's evidence is not polluted by retry traffic on the
    previous one.
    """
    remaining = [_normalise_sent_event(event) for event in sent]
    dit_seconds = timing.dit_seconds(character_wpm)
    updated: list[dict[str, Any]] = []

    cursor = 0
    for raw_entry in entries:
        entry = dict(raw_entry)
        target = str(entry.get("target", ""))
        exercise_events, cursor = _consume_events_for_target(target, remaining, cursor)
        attempts = _segment_attempts(target, exercise_events)
        analysed_attempts = [
            _analyse_attempt(target, attempt, key_events=key_events, dit_seconds=dit_seconds)
            for attempt in attempts
        ]
        selected_index = _select_attempt_index(analysed_attempts)
        selected = analysed_attempts[selected_index] if selected_index is not None else None

        entry["attempts"] = analysed_attempts
        entry["analysis"] = _build_exercise_analysis(
            entry,
            selected,
            attempt_count=len(analysed_attempts),
            selected_attempt_index=selected_index,
        )
        updated.append(entry)

    return updated


def _consume_events_for_target(
    target: str,
    sent: list[dict[str, Any]],
    cursor: int,
) -> tuple[list[dict[str, Any]], int]:
    steps = _expected_steps(target)
    if not steps:
        return [], cursor

    events: list[dict[str, Any]] = []
    progress = 0
    idx = cursor
    while idx < len(sent):
        event = sent[idx]
        events.append(event)
        symbol = str(event.get("symbol") or "?")
        leading = str(event.get("leading_gap") or "none")
        expected = steps[progress]
        symbol_matches = symbol == expected["symbol"]
        gap_matches = progress == 0 or leading == expected["leading"]
        if symbol_matches and gap_matches:
            progress += 1
            idx += 1
            if progress >= len(steps):
                return events, idx
            continue

        first = steps[0]
        progress = 1 if symbol == first["symbol"] else 0
        idx += 1

    return events, idx


def _segment_attempts(target: str, events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    steps = _expected_steps(target)
    if not events:
        return []
    if not steps:
        return [events]

    attempts: list[list[dict[str, Any]]] = []
    progress = 0
    for event in events:
        symbol = str(event.get("symbol") or "?")
        leading = str(event.get("leading_gap") or "none")
        start_new = False
        if symbol == steps[0]["symbol"]:
            if progress == 0:
                start_new = True
            else:
                expected = steps[progress] if progress < len(steps) else None
                continues = (
                    expected is not None
                    and symbol == expected["symbol"]
                    and leading == expected["leading"]
                )
                start_new = not continues
        if start_new or not attempts:
            attempts.append([])
        attempts[-1].append(event)

        expected = steps[progress] if progress < len(steps) else None
        if (
            expected
            and symbol == expected["symbol"]
            and (progress == 0 or leading == expected["leading"])
        ):
            progress += 1
            if progress >= len(steps):
                progress = 0
        else:
            progress = 1 if symbol == steps[0]["symbol"] else 0

    return attempts


_COMBINED_WEIGHTS = {
    "cadence-send": (0.40, 0.30, 0.20, 0.05, 0.05),
    "copy-key": (0.55, 0.10, 0.20, 0.10, 0.05),
}


def _analyse_attempt(
    target: str,
    events: list[dict[str, Any]],
    *,
    key_events: list[dict[str, Any]],
    dit_seconds: float,
    mode: str = "cadence-send",
) -> dict[str, Any]:
    expected_steps = _expected_steps(target)
    expected_symbols = "".join(step["symbol"] for step in expected_steps)
    sent_symbols = "".join(str(event.get("symbol") or "?") for event in events)
    symbol_available = max(len(expected_symbols), len(sent_symbols))
    symbol_distance = _levenshtein(expected_symbols, sent_symbols)
    symbol_correct = max(0, symbol_available - symbol_distance)
    symbol_fraction = _fraction(symbol_correct, symbol_available)

    spacing_available = max(0, min(len(expected_steps), len(events)) - 1)
    spacing_correct = 0
    gap_values: list[float] = []
    gap_samples: list[dict[str, Any]] = []
    for idx in range(1, min(len(expected_steps), len(events))):
        expected = expected_steps[idx]["leading"]
        actual = str(events[idx].get("leading_gap") or "none")
        if actual == expected:
            spacing_correct += 1
        gap_ms = _leading_gap_ms(events[idx - 1], events[idx])
        if gap_ms is not None and dit_seconds > 0:
            gap_units = gap_ms / (dit_seconds * 1000)
            expected_units = 7 if expected == "word" else 3
            score = _gap_readability_score(
                expected=expected,
                actual=actual,
                gap_units=gap_units,
            )
            gap_values.append(score)
            gap_samples.append(
                {
                    "index": idx,
                    "expected": expected,
                    "actual": actual,
                    "gap_ms": round(gap_ms, 3),
                    "gap_units": round(gap_units, 3),
                    "expected_units": expected_units,
                    "readability_fraction": round(score, 6),
                }
            )
    spacing_fraction = _fraction(spacing_correct, spacing_available, default=1.0)
    gap_timing_fraction = _mean(gap_values, default=1.0)

    formation_fraction = _formation_fraction_for_attempt(events, key_events, dit_seconds)
    decoded = [str(event.get("symbol") or "?") for event in events]
    decode_health = _fraction(
        sum(1 for symbol in decoded if symbol != "?"),
        len(decoded),
        default=1.0,
    )
    complete = _attempt_is_complete(expected_steps, events)

    w_sym, w_spc, w_form, w_gap, w_dec = _COMBINED_WEIGHTS.get(
        mode, _COMBINED_WEIGHTS["cadence-send"]
    )
    combined = (
        (w_sym * symbol_fraction)
        + (w_spc * spacing_fraction)
        + (w_form * formation_fraction)
        + (w_gap * gap_timing_fraction)
        + (w_dec * decode_health)
    )
    return {
        "events": [
            {
                "symbol": str(event.get("symbol") or "?"),
                "pattern": str(event.get("pattern") or ""),
                "started_at": event.get("started_at"),
                "ended_at": event.get("ended_at"),
                "leading_gap": str(event.get("leading_gap") or "none"),
            }
            for event in events
        ],
        "gaps": gap_samples,
        "complete": complete,
        "symbol_correct_units": symbol_correct,
        "symbol_available_units": symbol_available,
        "symbol_edit_distance": symbol_distance,
        "spacing_correct_units": spacing_correct,
        "spacing_available_units": spacing_available,
        "symbol_fraction": round(symbol_fraction, 6),
        "spacing_fraction": round(spacing_fraction, 6),
        "formation_fraction": round(formation_fraction, 6),
        "gap_timing_fraction": round(gap_timing_fraction, 6),
        "decode_health": round(decode_health, 6),
        "combined_fraction": round(max(0.0, min(1.0, combined)), 6),
    }


def _build_exercise_analysis(
    entry: dict[str, Any],
    selected: dict[str, Any] | None,
    *,
    attempt_count: int,
    selected_attempt_index: int | None,
) -> dict[str, Any]:
    if selected is None:
        return {
            "version": ANALYSIS_VERSION,
            "saved": True,
            "attempt_count": 0,
            "selected_attempt_index": None,
            "selected_attempt_reason": "none",
            "symbol_fraction": 0.0,
            "spacing_fraction": 0.0,
            "formation_fraction": 0.0,
            "gap_timing_fraction": 0.0,
            "decode_health": 0.0,
            "combined_fraction": 0.0,
            "evidence": 0.0,
            "band_state": "low",
            "burden_band": _coerce_int(entry.get("burden_band"), 0),
            "gear": _coerce_int(entry.get("gear"), 0),
        }

    burden_score = _coerce_int(entry.get("burden_score"), 0)
    burden_band = _coerce_int(entry.get("burden_band"), 0)
    gear = _coerce_int(entry.get("gear"), 0)
    combined = float(selected["combined_fraction"])
    burden_weight = 1.0 + log1p(max(0, burden_score))
    evidence = combined * burden_weight
    return {
        "version": ANALYSIS_VERSION,
        "saved": True,
        "attempt_count": attempt_count,
        "selected_attempt_index": selected_attempt_index,
        "selected_attempt_reason": "latest-complete" if selected["complete"] else "best-partial",
        "symbol_fraction": selected["symbol_fraction"],
        "spacing_fraction": selected["spacing_fraction"],
        "formation_fraction": selected["formation_fraction"],
        "gap_timing_fraction": selected["gap_timing_fraction"],
        "decode_health": selected["decode_health"],
        "combined_fraction": selected["combined_fraction"],
        "evidence": round(evidence, 6),
        "band_state": _band_state(combined),
        "burden_band": burden_band,
        "gear": gear,
    }


def _select_attempt_index(attempts: list[dict[str, Any]]) -> int | None:
    if not attempts:
        return None
    for idx in range(len(attempts) - 1, -1, -1):
        if attempts[idx].get("complete") is True:
            return idx
    return max(range(len(attempts)), key=lambda idx: float(attempts[idx]["combined_fraction"]))


def _formation_fraction_for_attempt(
    events: list[dict[str, Any]],
    key_events: list[dict[str, Any]],
    dit_seconds: float,
) -> float:
    if not events:
        return 0.0
    starts = [event.get("started_at") for event in events]
    ends = [event.get("ended_at") for event in events]
    numeric_starts = [
        float(v) for v in starts if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    numeric_ends = [
        float(v) for v in ends if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    if not numeric_starts or not numeric_ends:
        return 0.0
    start = min(numeric_starts)
    end = max(numeric_ends)
    scores: list[float] = []
    for event in key_events:
        if not isinstance(event, dict):
            continue
        if event.get("pressed") is not False:
            continue
        kind = event.get("kind")
        if kind not in {"dit", "dah"}:
            continue
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
            continue
        if not start <= float(timestamp) <= end:
            continue
        duration_ms = _key_duration_ms(event)
        if duration_ms is None:
            continue
        ideal_ms = (1 if kind == "dit" else 3) * dit_seconds * 1000
        scores.append(_ratio_score(duration_ms, ideal_ms, tolerance=0.45))
    return _mean(scores, default=0.0)


def _key_duration_ms(event: dict[str, Any]) -> float | None:
    raw = event.get("duration_ms")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    started = event.get("started_at")
    ended = event.get("ended_at")
    if (
        isinstance(started, (int, float))
        and not isinstance(started, bool)
        and isinstance(ended, (int, float))
        and not isinstance(ended, bool)
    ):
        return max(0.0, (float(ended) - float(started)) * 1000)
    return None


def _leading_gap_ms(prev: dict[str, Any], current: dict[str, Any]) -> float | None:
    prev_end = prev.get("ended_at")
    current_start = current.get("started_at")
    if (
        isinstance(prev_end, (int, float))
        and not isinstance(prev_end, bool)
        and isinstance(current_start, (int, float))
        and not isinstance(current_start, bool)
    ):
        return max(0.0, (float(current_start) - float(prev_end)) * 1000)
    return None


def _ratio_score(actual: float, ideal: float, *, tolerance: float) -> float:
    if ideal <= 0:
        return 0.0
    error = abs(actual - ideal) / ideal
    return max(0.0, min(1.0, 1.0 - (error / tolerance)))


def _gap_readability_score(*, expected: str, actual: str, gap_units: float) -> float:
    """Score gap readability in dit-units, not metronomic exactness.

    A readable fist needs consistent separation: character gaps should
    stay clearly character-sized and word gaps should be unmistakably
    longer. Exact 3- and 7-unit matches are useful, but less important
    than producing gaps the decoder and another operator can separate.
    """
    if actual != expected:
        return 0.0
    if expected == "word":
        if gap_units >= 6.0:
            return 1.0
        if gap_units >= 5.0:
            return 0.75 + ((gap_units - 5.0) * 0.25)
        if gap_units >= 4.0:
            return 0.35 + ((gap_units - 4.0) * 0.40)
        return max(0.0, gap_units / 4.0 * 0.35)
    if expected == "character":
        if 2.0 <= gap_units <= 5.0:
            return 1.0
        if 1.0 <= gap_units < 2.0:
            return 0.5 + ((gap_units - 1.0) * 0.5)
        if 5.0 < gap_units <= 6.0:
            return 1.0 - ((gap_units - 5.0) * 0.5)
        if 6.0 < gap_units <= 7.0:
            return 0.5 - ((gap_units - 6.0) * 0.5)
    return 0.0


def _expected_steps(exercise: str) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    for word_idx, word in enumerate(str(exercise).split(" ")):
        if not word:
            continue
        for ch_idx, symbol in enumerate(word):
            if not steps:
                leading = "none"
            elif ch_idx == 0:
                leading = "word"
            else:
                leading = "character"
            steps.append({"symbol": symbol, "leading": leading})
    return steps


def _attempt_is_complete(
    expected_steps: list[dict[str, str]], events: list[dict[str, Any]]
) -> bool:
    if len(events) < len(expected_steps):
        return False
    for idx, expected in enumerate(expected_steps):
        event = events[idx]
        symbol = str(event.get("symbol") or "?")
        leading = str(event.get("leading_gap") or "none")
        if symbol != expected["symbol"]:
            return False
        if idx > 0 and leading != expected["leading"]:
            return False
    return True


def _normalise_sent_event(event: dict[str, Any]) -> dict[str, Any]:
    symbol = event.get("symbol")
    return {
        "symbol": symbol if isinstance(symbol, str) and symbol else "?",
        "pattern": event.get("pattern") if isinstance(event.get("pattern"), str) else "",
        "started_at": event.get("started_at"),
        "ended_at": event.get("ended_at"),
        "leading_gap": (
            event.get("leading_gap") if isinstance(event.get("leading_gap"), str) else "none"
        ),
    }


def record_claimed_set_key(record: dict[str, Any]) -> str:
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
    mode: str = "cadence-send",
) -> dict[str, Any]:
    matching = _matching_records(records, claimed_set_key=claimed_set_key, mode=mode)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    window = matching[: max(0, window_size)]

    band_entries: dict[int, list[tuple[float, str, int]]] = {}
    channel_totals: dict[int, dict[str, list[float]]] = {}
    for session in window:
        gears = _gears_from_generation(session.get("generation"))
        exercises = session.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            band = exercise.get("burden_band")
            if not isinstance(band, int) or isinstance(band, bool):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("saved") is not True:
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            gear = gears.get(band, _coerce_int(exercise.get("gear"), 0))
            state = analysis.get("band_state")
            band_entries.setdefault(band, []).append((float(fraction), str(state), gear))
            totals = channel_totals.setdefault(
                band,
                {
                    "symbol_fraction": [],
                    "spacing_fraction": [],
                    "formation_fraction": [],
                    "gap_timing_fraction": [],
                    "decode_health": [],
                },
            )
            for key in totals:
                value = analysis.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    totals[key].append(float(value))

    bands: list[dict[str, Any]] = []
    for band in sorted(band_entries):
        entries = band_entries[band]
        fractions = [f for f, _, _ in entries]
        channel_means = {
            key: round(_mean(values, default=0.0), 6)
            for key, values in channel_totals.get(band, {}).items()
        }
        bands.append(
            {
                "burden_band": band,
                "recent_fractions": [round(f, 6) for f in fractions],
                "strong_streak": _streak_at_current_gear(entries, lambda v: v >= STRONG_FRACTION),
                "low_streak": _streak_at_current_gear(entries, lambda v: v < LOW_FRACTION),
                **channel_means,
            }
        )

    return {
        "claimed_set_key": claimed_set_key,
        "session_count": len(matching),
        "window_size": window_size,
        "sessions_used": len(window),
        "bands": bands,
    }


def load_band_history(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    mode: str = "cadence-send",
) -> dict[str, Any]:
    """Chronological per-band history for one claimed-set key.

    Mirrors :func:`copy_653.sequence.exercise_analysis.load_band_history`
    so the Settings full-history modal renders identically on the Key
    side. Each cell carries the session's ``combined_fraction`` plus the
    gear that band ran at; gear-change events come back as a separate
    chronological list. Records with no analysis surface as ``fraction
    = None`` and the cell renders as missing client-side.
    """
    matching = _matching_records(records, claimed_set_key=claimed_set_key, mode=mode)
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
                gear = _coerce_int(exercise.get("gear"), 0)

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


def latest_gears_for_claimed_set(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    mode: str = "cadence-send",
) -> dict[int, int]:
    matching = _matching_records(records, claimed_set_key=claimed_set_key, mode=mode)
    if not matching:
        return {}
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return _gears_from_generation(matching[0].get("generation"))


def is_ready_for_next_symbol(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    strong_fraction: float = STRONG_FRACTION,
    n_strong_required: int = N_CLEAN_RUNS_FOR_SHIFT,
    max_gear: int = MAX_GEAR,
    window_size: int = DEFAULT_EVIDENCE_WINDOW_SIZE,
    mode: str = "cadence-send",
) -> bool:
    """Whether send evidence says the learner is ready for the next symbol.

    Sibling of
    :func:`copy_653.sequence.exercise_analysis.is_ready_for_next_symbol`,
    reading ``cadence-send`` records instead of ``koch-exercise``. The
    Key (send) nudge is deliberately decoupled from the listen nudge —
    send is a different skill, and the two channels can sit at
    different points in the curriculum (philosophy §3.7).

    Thresholds default to the listen-side constants. They are inherited
    deliberately for the first cut so the two surfaces start at the same
    bar, but send and listen are unlikely to need identical dials in
    the long run — if real data shows this rule firing too eagerly or
    too rarely on the send side, override these parameters here rather
    than retuning the listen-side constants.

    Returns ``True`` when, for the given ``claimed_set_key``:

    * every burden band's current send gear is at ``max_gear``, and
    * each band has at least ``n_strong_required`` recent sessions with
      ``combined_fraction >= strong_fraction`` in a ``window_size``-deep
      window, and
    * each band's most-recent recorded fraction is also
      ``>= strong_fraction``.

    Returns ``False`` on insufficient evidence (empty records, empty
    ``claimed_set_key``, no band data) — the WS layer only needs a
    boolean and "no nudge" is the safe default.
    """
    if not claimed_set_key:
        return False

    current_gears = latest_gears_for_claimed_set(
        records, claimed_set_key=claimed_set_key, mode=mode
    )
    if not current_gears:
        return False
    if any(gear < max_gear for gear in current_gears.values()):
        return False

    evidence = load_band_evidence(
        records,
        claimed_set_key=claimed_set_key,
        window_size=window_size,
        mode=mode,
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
    resolved = dict(current_gears)
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


def _matching_records(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    mode: str = "cadence-send",
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("mode") == mode
        and record_claimed_set_key(record) == claimed_set_key
    ]


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


def _band_state(value: float) -> str:
    if value < LOW_FRACTION:
        return "low"
    if value < 0.85:
        return "building"
    if value < STRONG_FRACTION:
        return "steady"
    if value < 1.0:
        return "strong"
    return "exact"


def _fraction(correct: int, available: int, *, default: float = 0.0) -> float:
    if available <= 0:
        return default
    return max(0.0, min(1.0, correct / available))


def _mean(values: list[float], *, default: float) -> float:
    if not values:
        return default
    return sum(values) / len(values)


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default
