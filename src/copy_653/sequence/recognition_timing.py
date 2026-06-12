"""Response-time aggregation for saved Symbol Recognition sessions."""

from __future__ import annotations

from typing import Any

from copy_653.sequence.exercise_analysis import record_claimed_set_key
from copy_653.sequence.recognition_progression import _gear_from_generation
from copy_653.sequence.recognition_windowing import (
    OUTCOME_CAUGHT_CORRECT,
    OUTCOME_CAUGHT_SUBSTITUTION,
    OUTCOME_CORRECT,
    OUTCOME_MISS,
    OUTCOME_SUBSTITUTION,
    _ordered_symbols,
)

TIMING_TREND_SESSION_WINDOW = 5
TIMING_TREND_MIN_DELTA_MS = 250


def load_recognition_timing(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    trend_window_size: int = TIMING_TREND_SESSION_WINDOW,
) -> dict[str, Any]:
    """Aggregate response-time evidence across recognition sessions.

    Timing is derived entirely from saved records: the played target
    schedule in ``symbols`` and each exercise's committed
    ``voice_capture``. Newer records use the first partial/symbol timing
    when present; older records fall back to the final speech-recognition
    timestamp. The latency is measured from the final played symbol's
    ``t_off`` so Gear 1 pairs and later longer prompts are compared from
    the moment the audio target has actually finished.
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

    lifetime_stats = _recognition_timing_stats(matching)
    recent_stats = _recognition_timing_stats(recent)
    previous_stats = _recognition_timing_stats(previous)

    return {
        "claimed_set_key": claimed_set_key,
        "exercises_used": lifetime_stats["exercises_used"],
        "trend_window_size": window_size,
        "recent_exercises_used": recent_stats["exercises_used"],
        "previous_exercises_used": previous_stats["exercises_used"],
        "targets": _sorted_timing_rows(
            lifetime_stats["targets"],
            recent_stats["targets"],
            previous_stats["targets"],
        ),
    }


def _recognition_timing_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    targets: dict[tuple[int, str], list[dict[str, Any]]] = {}
    exercises_used = 0

    for record in records:
        symbols_by_exercise = _symbols_by_exercise(record.get("symbols") or [])
        recognition_window_ms = _recognition_window_ms(record)
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            index = exercise.get("index")
            if not isinstance(index, int) or isinstance(index, bool):
                continue
            symbols = symbols_by_exercise.get(index, [])
            target_symbols = _target_symbols(exercise, symbols)
            target = "".join(target_symbols)
            if not target:
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("has_evidence") is not True:
                continue
            gear = _coerce_int(
                exercise.get("gear"), _gear_from_generation(record.get("generation")) or 0
            )
            attempts = _timing_attempts_for_exercise(
                exercise,
                symbols,
                analysis,
                gear=gear,
                fallback_target=target,
                recognition_window_ms=recognition_window_ms,
            )
            for unit, attempt in attempts:
                targets.setdefault((gear, unit), []).append(attempt)
                exercises_used += 1

    return {"targets": targets, "exercises_used": exercises_used}


def _timing_attempts_for_exercise(
    exercise: dict[str, Any],
    symbols: list[dict[str, Any]],
    analysis: dict[str, Any],
    *,
    gear: int,
    fallback_target: str,
    recognition_window_ms: int,
) -> list[tuple[str, dict[str, Any]]]:
    if gear == 0:
        per_symbol = _per_symbol_timing_attempts(
            exercise,
            symbols,
            analysis,
            recognition_window_ms=recognition_window_ms,
        )
        if per_symbol:
            return per_symbol

    response_t = _exercise_response_time(exercise)
    target_t_off = _target_end_time(symbols)
    if response_t is None or target_t_off is None:
        return []
    latency_ms = max(0, int(round((response_t - target_t_off) * 1000)))
    return [
        (
            fallback_target,
            {
                "latency_ms": latency_ms,
                "late": recognition_window_ms > 0 and latency_ms > recognition_window_ms,
                "correct": _analysis_is_exact(analysis),
                "confused": bool(analysis.get("committed_confusions")),
                "missed": _analysis_has_miss(analysis),
            },
        )
    ]


def _per_symbol_timing_attempts(
    exercise: dict[str, Any],
    symbols: list[dict[str, Any]],
    analysis: dict[str, Any],
    *,
    recognition_window_ms: int,
) -> list[tuple[str, dict[str, Any]]]:
    symbol_events = _voice_symbol_events(exercise)
    if not symbol_events:
        return []
    slots = analysis.get("slots")
    slot_by_index: dict[Any, dict[str, Any]] = {}
    if isinstance(slots, list):
        slot_by_index = {slot.get("index"): slot for slot in slots if isinstance(slot, dict)}

    attempts: list[tuple[str, dict[str, Any]]] = []
    ordered = _ordered_symbols(symbols)
    for idx, target in enumerate(ordered, start=1):
        unit = str(target.get("symbol") or "").upper()
        if not unit:
            continue
        event_t = symbol_events.get(idx)
        target_t_off = target.get("t_off")
        if event_t is None or not isinstance(target_t_off, (int, float)):
            continue
        latency_ms = max(0, int(round((event_t - float(target_t_off)) * 1000)))
        slot = slot_by_index.get(idx)
        outcome = slot.get("outcome") if isinstance(slot, dict) else ""
        attempts.append(
            (
                unit,
                {
                    "latency_ms": latency_ms,
                    "late": recognition_window_ms > 0 and latency_ms > recognition_window_ms,
                    "correct": outcome in (OUTCOME_CORRECT, OUTCOME_CAUGHT_CORRECT),
                    "confused": outcome in (OUTCOME_SUBSTITUTION, OUTCOME_CAUGHT_SUBSTITUTION),
                    "missed": outcome == OUTCOME_MISS,
                },
            )
        )
    return attempts


def _voice_symbol_events(exercise: dict[str, Any]) -> dict[int, float]:
    capture = exercise.get("voice_capture")
    if not isinstance(capture, list):
        return {}
    events: dict[int, float] = {}
    for entry in capture:
        if not isinstance(entry, dict):
            continue
        symbol_events = entry.get("symbol_events")
        if not isinstance(symbol_events, list):
            continue
        for event in symbol_events:
            if not isinstance(event, dict):
                continue
            index = event.get("index")
            event_t = event.get("t")
            if not isinstance(index, int) or isinstance(index, bool):
                continue
            if not isinstance(event_t, (int, float)) or isinstance(event_t, bool):
                continue
            events.setdefault(index, float(event_t))
    return events


def _sorted_timing_rows(
    lifetime: dict[tuple[int, str], list[dict[str, Any]]],
    recent: dict[tuple[int, str], list[dict[str, Any]]],
    previous: dict[tuple[int, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, attempts in lifetime.items():
        gear, target = key
        recent_attempts = recent.get(key, [])
        previous_attempts = previous.get(key, [])
        recent_median = _median_ms([a["latency_ms"] for a in recent_attempts])
        previous_median = _median_ms([a["latency_ms"] for a in previous_attempts])
        rows.append(
            {
                "gear": gear,
                "target": target,
                "count": len(attempts),
                "median_ms": _median_ms([a["latency_ms"] for a in attempts]),
                "recent_count": len(recent_attempts),
                "recent_median_ms": recent_median,
                "previous_count": len(previous_attempts),
                "previous_median_ms": previous_median,
                "trend": _timing_trend(recent_median, previous_median),
                "correct_count": sum(1 for a in attempts if a["correct"]),
                "confused_count": sum(1 for a in attempts if a["confused"]),
                "missed_count": sum(1 for a in attempts if a["missed"]),
                "late_count": sum(1 for a in attempts if a["late"]),
            }
        )
    rows.sort(key=lambda item: (-item["count"], item["gear"], item["target"]))
    return rows


def _symbols_by_exercise(symbols: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for entry in symbols:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("exercise_index")
        if isinstance(idx, int) and not isinstance(idx, bool):
            out.setdefault(idx, []).append(entry)
    return out


def _target_symbols(exercise: dict[str, Any], symbols: list[dict[str, Any]]) -> list[str]:
    ordered = _ordered_symbols(symbols)
    if ordered:
        return [str(entry["symbol"]).upper() for entry in ordered]
    target = exercise.get("target")
    if not isinstance(target, str):
        return []
    return _compact_symbol_string(target)


def _exercise_response_time(exercise: dict[str, Any]) -> float | None:
    capture = exercise.get("voice_capture")
    if not isinstance(capture, list):
        return None
    partial_times: list[float] = []
    symbol_event_times: list[float] = []
    final_times: list[float] = []
    for entry in capture:
        if not isinstance(entry, dict):
            continue
        first_partial_t = entry.get("first_partial_t")
        if isinstance(first_partial_t, (int, float)) and not isinstance(first_partial_t, bool):
            partial_times.append(float(first_partial_t))
        symbol_events = entry.get("symbol_events")
        if isinstance(symbol_events, list):
            for event in symbol_events:
                if not isinstance(event, dict):
                    continue
                event_t = event.get("t")
                if isinstance(event_t, (int, float)) and not isinstance(event_t, bool):
                    symbol_event_times.append(float(event_t))
        t = entry.get("t")
        if isinstance(t, (int, float)) and not isinstance(t, bool):
            final_times.append(float(t))
    if partial_times:
        return min(partial_times)
    if symbol_event_times:
        return min(symbol_event_times)
    return max(final_times) if final_times else None


def _target_end_time(symbols: list[dict[str, Any]]) -> float | None:
    times: list[float] = []
    for entry in symbols:
        if not isinstance(entry, dict):
            continue
        t_off = entry.get("t_off")
        if isinstance(t_off, (int, float)) and not isinstance(t_off, bool):
            times.append(float(t_off))
    return max(times) if times else None


def _recognition_window_ms(record: dict[str, Any]) -> int:
    generation = record.get("generation")
    if not isinstance(generation, dict):
        return 0
    recognition = generation.get("recognition")
    if not isinstance(recognition, dict):
        return 0
    value = recognition.get("recognition_time_ms")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 0
    return max(0, int(value))


def _analysis_is_exact(analysis: dict[str, Any]) -> bool:
    fraction = analysis.get("combined_fraction")
    return isinstance(fraction, (int, float)) and not isinstance(fraction, bool) and fraction >= 1


def _analysis_has_miss(analysis: dict[str, Any]) -> bool:
    counts = analysis.get("counts")
    if not isinstance(counts, dict):
        return False
    value = counts.get(OUTCOME_MISS)
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _median_ms(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return int(round((ordered[mid - 1] + ordered[mid]) / 2))


def _timing_trend(recent_median: int | None, previous_median: int | None) -> str:
    if recent_median is None or previous_median is None:
        return "insufficient"
    delta = recent_median - previous_median
    if delta <= -TIMING_TREND_MIN_DELTA_MS:
        return "improving"
    if delta >= TIMING_TREND_MIN_DELTA_MS:
        return "worsening"
    return "stable"


def _compact_symbol_string(value: str) -> list[str]:
    return [ch.upper() for ch in value if not ch.isspace()]


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default
