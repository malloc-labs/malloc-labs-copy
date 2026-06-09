"""Burden-debt profile derivation for saved recognition evidence.

This module is read-only analysis. It interprets existing Symbol
Recognition records into backend evidence about burdens, debt, and
confidence; it does not change generation or learner-facing progression.
"""

from __future__ import annotations

from collections import Counter
from collections import defaultdict
from datetime import datetime
from math import ceil
from typing import Any

from copy_653.audio import patterns
from copy_653.sequence.exercise_analysis import (
    DEFAULT_EVIDENCE_WINDOW_SIZE as DEFAULT_KOCH_BURDEN_WINDOW_SIZE,
    LOW_FRACTION,
    STRONG_FRACTION,
    _align,
    _symbols_only,
    load_confusion_pairs,
    record_claimed_set_key,
    strip_fixed_anchor,
)
from copy_653.sequence.listening_conditions import (
    KOCH_LISTENING_PROBE_VERSION,
    KOCH_PROBE_PHASE_CHALLENGE,
    LISTENING_CONDITION_DEFAULT,
    LISTENING_CONDITION_TEXTURED,
    RECOGNITION_LISTENING_PROBE_VERSION,
)
from copy_653.sequence.recognition_analysis import recognition_review_analysis

BURDEN_PROFILE_VERSION = "burden-profile-v1"
ATTENTION_RESPONSE_VERSION = "attention-response-v1"
ESTIMATED_TIME_VERSION = "recognition-estimated-time-v1"
DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE = 20
RECOGNITION_TARGET_FRACTION = 0.90
SETTLED_FUTURE_ACCURACY_LOW = 0.96
SETTLED_FUTURE_ACCURACY_HIGH = 0.98

DEBT_LOW = "low"
DEBT_MODERATE = "moderate"
DEBT_HIGH = "high"
DEBT_UNKNOWN = "unknown"

CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE = 8
MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE = 20
MIN_SYMBOL_RECENT_EXPOSURES_SIGNAL = 8
MIN_UNIT_EXERCISES_MEDIUM_CONFIDENCE = 4
MIN_UNIT_EXERCISES_HIGH_CONFIDENCE = 10
MIN_CONFUSION_EXPOSURES_MEDIUM_CONFIDENCE = 20
MIN_CONFUSION_EXPOSURES_HIGH_CONFIDENCE = 80

MODERATE_CONFUSION_COUNT = 2
HIGH_CONFUSION_COUNT = 4

ATTENTION_MIN_EXERCISES_PER_CONDITION = 4
ATTENTION_HELPED_DELTA = 0.05
ATTENTION_NEUTRAL_DELTA = 0.02
LISTENING_PROBE_VERSION = RECOGNITION_LISTENING_PROBE_VERSION
LISTENING_MIN_EXERCISES_PER_CONDITION = 2
LISTENING_MODERATE_DELTA = 0.05
LISTENING_HIGH_DELTA = 0.12
RHYTHM_PROBE_VERSION = "recognition-rhythm-v1"
RHYTHM_MIN_EXERCISES_PER_CONDITION = 2
RHYTHM_MODERATE_DELTA = 0.05
RHYTHM_HIGH_DELTA = 0.12
TRANSFER_MIN_RECOGNITION_SLOTS = 20
TRANSFER_MIN_KOCH_SYMBOL_UNITS = 8
TRANSFER_MODERATE_DELTA = 0.05
TRANSFER_HIGH_DELTA = 0.12
TRANSFER_LOW_ABSOLUTE_FRACTION = 0.85
TRANSFER_HIGH_ABSOLUTE_FRACTION = 0.70


def load_recognition_burden_profile(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE,
) -> dict[str, Any]:
    """Build a read-only burden debt profile from recognition records.

    The initial implementation intentionally uses only burden axes for
    which current recognition records already carry meaningful evidence:

    * symbol inventory
    * unit length
    * confusion pressure

    Listening-condition debt uses only controlled probe evidence. Rhythm can
    report baseline recognition history, but only tagged cadence-varied probes
    produce measured rhythm debt. Anchor and practice-transfer debt remain
    unknown until first-class probes or comparable condition evidence exist.
    """
    matching = _matching_recognition_records(records, claimed_set_key)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    recent = matching[: max(0, window_size)]
    koch_matching = _matching_koch_records(records, claimed_set_key)
    koch_matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    koch_recent = koch_matching[:DEFAULT_KOCH_BURDEN_WINDOW_SIZE]
    claimed_symbols = set(claimed_set_key.split())
    stats = _collect_stats(recent)
    koch_stats = _collect_koch_stats(koch_recent)
    listening_probe_rows = _collect_recognition_listening_probe_exercises(recent)
    rhythm_rows = _collect_recognition_rhythm_exercises(recent)
    symbol_stats = _collect_symbol_stats(records, symbols=claimed_symbols)
    recent_symbol_stats = _collect_symbol_stats(recent, symbols=claimed_symbols)
    symbol_inventory = _symbol_inventory_burden(symbol_stats, recent_symbol_stats)

    return {
        "version": BURDEN_PROFILE_VERSION,
        "claimed_set_key": claimed_set_key,
        "record_count": len(matching),
        "window_size": max(0, window_size),
        "records_used": len(recent),
        "estimated_time": _recognition_estimated_time(
            matching,
            claimed_set_key=claimed_set_key,
            symbol_inventory=symbol_inventory,
            window_size=max(0, window_size),
        ),
        "burdens": {
            "symbol_inventory": symbol_inventory,
            "unit_length": _unit_length_burden(stats),
            "confusion": _confusion_burden(stats),
            "signal": _recognition_listening_conditions_burden(listening_probe_rows),
            "rhythm": _recognition_rhythm_burden(rhythm_rows),
            "anchor": _recognition_anchor_burden(),
            "practice_transfer": _recognition_practice_transfer_burden(
                stats,
                koch_stats,
                koch_records_used=len(koch_recent),
            ),
        },
    }


def load_koch_burden_profile(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_KOCH_BURDEN_WINDOW_SIZE,
) -> dict[str, Any]:
    """Build a burden-axis profile from saved Koch Exercise evidence.

    Koch generation still runs on bands and gears, but the settings
    burden table should describe the listening burdens those mechanisms
    probe. Band and gear remain provenance inside the evidence strings.
    """
    matching = _matching_koch_records(records, claimed_set_key)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    recent = matching[: max(0, window_size)]
    stats = _collect_koch_stats(recent)
    lifetime_stats = _collect_koch_stats(matching)
    claimed_symbols = set(claimed_set_key.split())
    symbol_stats = _collect_koch_symbol_stats(matching, symbols=claimed_symbols)
    recent_symbol_stats = _collect_koch_symbol_stats(recent, symbols=claimed_symbols)
    listening_probe_rows = _collect_koch_listening_probe_exercises(recent)
    confusions = load_confusion_pairs(records, claimed_set_key=claimed_set_key)

    return {
        "version": BURDEN_PROFILE_VERSION,
        "claimed_set_key": claimed_set_key,
        "record_count": len(matching),
        "window_size": max(0, window_size),
        "records_used": len(recent),
        "burdens": {
            "symbol_inventory": _koch_symbol_inventory_burden(
                stats,
                lifetime_stats=lifetime_stats,
                symbol_stats=symbol_stats,
                recent_symbol_stats=recent_symbol_stats,
            ),
            "grouping": _koch_grouping_burden(stats, lifetime_stats=lifetime_stats),
            "unit_length": _koch_unit_length_burden(stats, lifetime_stats=lifetime_stats),
            "confusion": _koch_confusion_burden(confusions),
            "signal": _koch_listening_conditions_burden(listening_probe_rows),
            "rhythm": _unknown_burden("No Koch cadence-variation contrast probes yet."),
            "anchor": _unknown_burden("No Koch anchor-removal contrast probes yet."),
            "practice_transfer": _unknown_burden(
                "No linked Symbol Recognition to Koch Exercise transfer evidence yet."
            ),
        },
    }


def load_koch_attention_response(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_KOCH_BURDEN_WINDOW_SIZE,
) -> dict[str, Any]:
    """Compare Koch copy stability across saved per-exercise S/T conditions.

    This is deliberately separate from burden debt: the response may be
    helpful, neutral, or harmful, and lower S is not assumed to be worse.
    """
    matching = _matching_koch_records(records, claimed_set_key)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    recent = matching[: max(0, window_size)]
    exercises = _collect_koch_attention_exercises(recent)
    lower = [row for row in exercises if 2 <= row["s"] <= 6]
    higher = [row for row in exercises if 7 <= row["s"] <= 9]

    return {
        "version": ATTENTION_RESPONSE_VERSION,
        "claimed_set_key": claimed_set_key,
        "record_count": len(matching),
        "window_size": max(0, window_size),
        "records_used": len(recent),
        "exercise_count": len(exercises),
        "conditions": [
            _koch_attention_condition(
                key="lower_s",
                label="Lower S / more texture",
                rows=lower,
                reference_rows=higher,
            ),
            _koch_attention_condition(
                key="higher_s",
                label="Higher S / cleaner signal",
                rows=higher,
                reference_rows=lower,
            ),
        ],
    }


def load_recognition_attention_response(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    window_size: int = DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE,
) -> dict[str, Any]:
    """Compare recognition stability across saved per-exercise S/T conditions."""
    matching = _matching_recognition_records(records, claimed_set_key)
    matching.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    recent = matching[: max(0, window_size)]
    exercises = _collect_recognition_attention_exercises(recent)
    lower = [row for row in exercises if 2 <= row["s"] <= 6]
    higher = [row for row in exercises if 7 <= row["s"] <= 9]

    return {
        "version": ATTENTION_RESPONSE_VERSION,
        "claimed_set_key": claimed_set_key,
        "record_count": len(matching),
        "window_size": max(0, window_size),
        "records_used": len(recent),
        "exercise_count": len(exercises),
        "conditions": [
            _recognition_attention_condition(
                key="lower_s",
                label="Lower S / more texture",
                rows=lower,
                reference_rows=higher,
            ),
            _recognition_attention_condition(
                key="higher_s",
                label="Higher S / cleaner signal",
                rows=higher,
                reference_rows=lower,
            ),
        ],
    }


def _recognition_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if isinstance(record, dict) and record.get("mode") == "recognition"
    ]


def _matching_recognition_records(
    records: list[dict[str, Any]],
    claimed_set_key: str,
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("mode") == "recognition"
        and record_claimed_set_key(record) == claimed_set_key
    ]


def _matching_koch_records(
    records: list[dict[str, Any]],
    claimed_set_key: str,
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("mode") == "koch-exercise"
        and record.get("warm_up") is not True
        and record_claimed_set_key(record) == claimed_set_key
    ]


def _collect_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    symbol_slots: dict[str, Counter[str]] = defaultdict(Counter)
    unit_attempts: dict[int, list[float]] = defaultdict(list)
    committed_confusions: Counter[tuple[str, str]] = Counter()
    caught_confusions: Counter[tuple[str, str]] = Counter()

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

            gear = _coerce_int(exercise.get("gear"), _record_gear(record))
            fraction = analysis.get("combined_fraction")
            if isinstance(fraction, (int, float)) and not isinstance(fraction, bool):
                unit_attempts[gear].append(float(fraction))

            slots = analysis.get("slots")
            if isinstance(slots, list):
                for slot in slots:
                    if not isinstance(slot, dict):
                        continue
                    truth = slot.get("truth")
                    outcome = slot.get("outcome")
                    if isinstance(truth, str) and truth and isinstance(outcome, str):
                        symbol_slots[truth.upper()][outcome] += 1

            # Confusion debt is a Settings/reporting view, so use the same
            # recovery-softened stream as the standalone Recognition
            # Confusions panel. Symbol and unit-length debt above still use
            # the strict saved analysis.
            confusion_analysis = _review_analysis_for_exercise(exercise)
            for pair in confusion_analysis.get("committed_confusions") or []:
                _tally_pair(committed_confusions, pair)
            for pair in confusion_analysis.get("caught_confusions") or []:
                _tally_pair(caught_confusions, pair)

    return {
        "symbol_slots": symbol_slots,
        "unit_attempts": unit_attempts,
        "committed_confusions": committed_confusions,
        "caught_confusions": caught_confusions,
    }


def _review_analysis_for_exercise(exercise: dict[str, Any]) -> dict[str, Any]:
    review = exercise.get("review_analysis")
    if isinstance(review, dict):
        return review
    return recognition_review_analysis(exercise)


def _collect_koch_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    symbol_correct = 0
    symbol_available = 0
    spacing_correct = 0
    spacing_available = 0
    band_attempts: dict[int, list[tuple[float, int]]] = defaultdict(list)
    exercise_count = 0

    for record in records:
        session_gears = _koch_gears_from_generation(record.get("generation"))
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("saved") is not True:
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue

            symbol_correct += _coerce_int(analysis.get("symbol_correct_units"), 0)
            symbol_available += _coerce_int(analysis.get("symbol_available_units"), 0)
            spacing_correct += _coerce_int(analysis.get("spacing_correct_units"), 0)
            spacing_available += _coerce_int(analysis.get("spacing_available_units"), 0)

            band = _coerce_int(exercise.get("burden_band"), 0)
            gear = session_gears.get(band, _coerce_int(exercise.get("gear"), 0))
            if band > 0:
                band_attempts[band].append((float(fraction), gear))
            exercise_count += 1

    return {
        "symbol_correct": symbol_correct,
        "symbol_available": symbol_available,
        "spacing_correct": spacing_correct,
        "spacing_available": spacing_available,
        "band_attempts": band_attempts,
        "exercise_count": exercise_count,
    }


def _collect_koch_symbol_stats(
    records: list[dict[str, Any]],
    *,
    symbols: set[str],
) -> dict[str, Any]:
    symbol_slots: dict[str, Counter[str]] = defaultdict(Counter)
    introduced_at: dict[str, str] = {}

    for record in sorted(records, key=lambda r: str(r.get("started_at") or "")):
        started_at = str(record.get("started_at") or "")
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("saved") is not True:
                continue
            played = str(exercise.get("played") or "")
            answer = str(exercise.get("answer") or "")
            truth = _symbols_only(strip_fixed_anchor(played))
            typed = _symbols_only(strip_fixed_anchor(answer))
            if not truth:
                continue
            for op, truth_symbol, _typed_symbol in _align(truth, typed):
                if not truth_symbol:
                    continue
                symbol = truth_symbol.upper()
                if symbols and symbol not in symbols:
                    continue
                if op == "match":
                    outcome = "correct"
                elif op == "sub":
                    outcome = "substitution"
                elif op == "del":
                    outcome = "miss"
                else:
                    continue
                symbol_slots[symbol][outcome] += 1
                introduced_at.setdefault(symbol, started_at)

    return {
        "symbol_slots": symbol_slots,
        "introduced_at": introduced_at,
    }


def _collect_koch_attention_exercises(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            s = _coerce_int(exercise.get("s"), 0)
            t = _coerce_int(exercise.get("t"), 0)
            if not (2 <= s <= 9 and 1 <= t <= 9):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("saved") is not True:
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            rows.append(
                {
                    "s": s,
                    "t": t,
                    "combined_fraction": float(fraction),
                    "symbol_correct": _coerce_int(analysis.get("symbol_correct_units"), 0),
                    "symbol_available": _coerce_int(analysis.get("symbol_available_units"), 0),
                    "spacing_correct": _coerce_int(analysis.get("spacing_correct_units"), 0),
                    "spacing_available": _coerce_int(analysis.get("spacing_available_units"), 0),
                    "burden_band": _coerce_int(exercise.get("burden_band"), 0),
                }
            )
    return rows


def _collect_koch_listening_probe_exercises(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        generation = record.get("generation")
        probe = generation.get("listening_probe") if isinstance(generation, dict) else None
        if not isinstance(probe, dict) or probe.get("version") != KOCH_LISTENING_PROBE_VERSION:
            continue
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            if exercise.get("listening_probe") != KOCH_LISTENING_PROBE_VERSION:
                continue
            condition = exercise.get("listening_condition")
            if condition not in {LISTENING_CONDITION_DEFAULT, LISTENING_CONDITION_TEXTURED}:
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("saved") is not True:
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            rows.append(
                {
                    "condition": condition,
                    "probe_phase": str(exercise.get("probe_phase") or ""),
                    "s": _coerce_int(exercise.get("s"), 0),
                    "t": _coerce_int(exercise.get("t"), 0),
                    "combined_fraction": float(fraction),
                    "symbol_correct": _coerce_int(analysis.get("symbol_correct_units"), 0),
                    "symbol_available": _coerce_int(analysis.get("symbol_available_units"), 0),
                    "spacing_correct": _coerce_int(analysis.get("spacing_correct_units"), 0),
                    "spacing_available": _coerce_int(analysis.get("spacing_available_units"), 0),
                    "burden_band": _coerce_int(exercise.get("burden_band"), 0),
                }
            )
    return rows


def _collect_recognition_attention_exercises(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            s = _coerce_int(exercise.get("s"), 0)
            t = _coerce_int(exercise.get("t"), 0)
            if not (2 <= s <= 9 and 1 <= t <= 9):
                continue
            analysis = exercise.get("analysis")
            if (
                not isinstance(analysis, dict)
                or analysis.get("saved") is not True
                or analysis.get("has_evidence") is not True
            ):
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            counts = analysis.get("counts")
            if not isinstance(counts, dict):
                counts = {}
            rows.append(
                {
                    "s": s,
                    "t": t,
                    "combined_fraction": float(fraction),
                    "correct": _coerce_int(counts.get("correct"), 0)
                    + _coerce_int(counts.get("caught_correct"), 0),
                    "substitutions": _coerce_int(counts.get("substitution"), 0)
                    + _coerce_int(counts.get("caught_substitution"), 0),
                    "misses": _coerce_int(counts.get("miss"), 0),
                    "slot_count": sum(_coerce_int(value, 0) for value in counts.values()),
                }
            )
    return rows


def _collect_recognition_listening_probe_exercises(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        generation = record.get("generation")
        probe = generation.get("listening_probe") if isinstance(generation, dict) else None
        if not isinstance(probe, dict) or probe.get("version") != LISTENING_PROBE_VERSION:
            continue
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            if exercise.get("listening_probe") != LISTENING_PROBE_VERSION:
                continue
            condition = exercise.get("listening_condition")
            if condition not in {LISTENING_CONDITION_DEFAULT, LISTENING_CONDITION_TEXTURED}:
                continue
            analysis = exercise.get("analysis")
            if (
                not isinstance(analysis, dict)
                or analysis.get("saved") is not True
                or analysis.get("has_evidence") is not True
            ):
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            counts = analysis.get("counts")
            if not isinstance(counts, dict):
                counts = {}
            rows.append(
                {
                    "condition": condition,
                    "s": _coerce_int(exercise.get("s"), 0),
                    "t": _coerce_int(exercise.get("t"), 0),
                    "combined_fraction": float(fraction),
                    "correct": _coerce_int(counts.get("correct"), 0)
                    + _coerce_int(counts.get("caught_correct"), 0),
                    "substitutions": _coerce_int(counts.get("substitution"), 0)
                    + _coerce_int(counts.get("caught_substitution"), 0),
                    "misses": _coerce_int(counts.get("miss"), 0),
                    "slot_count": sum(_coerce_int(value, 0) for value in counts.values()),
                }
            )
    return rows


def _collect_recognition_rhythm_exercises(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        generation = record.get("generation")
        probe = generation.get("rhythm_probe") if isinstance(generation, dict) else None
        record_audio = record.get("audio")
        record_cadence = (
            _coerce_int(record_audio.get("cadence_variation"), 0)
            if isinstance(record_audio, dict)
            else 0
        )
        baseline_cadence = _coerce_int(
            probe.get("baseline_cadence_variation") if isinstance(probe, dict) else None,
            record_cadence,
        )
        generation_is_tagged = (
            isinstance(probe, dict) and probe.get("version") == RHYTHM_PROBE_VERSION
        )
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = exercise.get("analysis")
            if (
                not isinstance(analysis, dict)
                or analysis.get("saved") is not True
                or analysis.get("has_evidence") is not True
            ):
                continue
            fraction = analysis.get("combined_fraction")
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
                continue
            counts = analysis.get("counts")
            if not isinstance(counts, dict):
                counts = {}

            exercise_probe = exercise.get("rhythm_probe")
            cadence_variation = _coerce_int(
                exercise.get("cadence_variation"),
                baseline_cadence,
            )
            is_probe = generation_is_tagged and exercise_probe == RHYTHM_PROBE_VERSION
            rows.append(
                {
                    "condition": "probe" if is_probe else "baseline",
                    "cadence_variation": cadence_variation,
                    "baseline_cadence_variation": baseline_cadence,
                    "combined_fraction": float(fraction),
                    "correct": _coerce_int(counts.get("correct"), 0)
                    + _coerce_int(counts.get("caught_correct"), 0),
                    "substitutions": _coerce_int(counts.get("substitution"), 0)
                    + _coerce_int(counts.get("caught_substitution"), 0),
                    "misses": _coerce_int(counts.get("miss"), 0),
                    "slot_count": sum(_coerce_int(value, 0) for value in counts.values()),
                }
            )
    return rows


def _koch_attention_condition(
    *,
    key: str,
    label: str,
    rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = _koch_attention_metrics(rows)
    reference = _koch_attention_metrics(reference_rows)
    confidence = _confidence_from_count(
        len(rows),
        medium=ATTENTION_MIN_EXERCISES_PER_CONDITION,
        high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
    )
    axes = {
        "symbols": _koch_attention_axis(
            metrics,
            reference,
            "symbol_fraction",
            "exercise_count",
        ),
        "grouping": _koch_attention_axis(
            metrics,
            reference,
            "grouping_fraction",
            "spacing_available_units",
        ),
        "unit_length": _koch_attention_axis(
            metrics,
            reference,
            "unit_length_fraction",
            "unit_length_exercise_count",
        ),
        "overall": _koch_attention_axis(
            metrics,
            reference,
            "overall_fraction",
            "exercise_count",
        ),
    }
    st_range = _format_st_range(rows)
    return {
        "key": key,
        "label": label,
        "st_range": st_range,
        "confidence": confidence,
        "exercise_count": len(rows),
        "reference_count": len(reference_rows),
        "axes": axes,
        "metrics": metrics,
        "reference_metrics": reference,
        "evidence": [
            _koch_attention_evidence(label, st_range, metrics, rows, reference_rows),
        ],
    }


def _recognition_attention_condition(
    *,
    key: str,
    label: str,
    rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = _recognition_attention_metrics(rows)
    reference = _recognition_attention_metrics(reference_rows)
    confidence = _confidence_from_count(
        len(rows),
        medium=ATTENTION_MIN_EXERCISES_PER_CONDITION,
        high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
    )
    axes = {
        "accuracy": _koch_attention_axis(
            metrics,
            reference,
            "accuracy_fraction",
            "exercise_count",
        ),
        "misses": _koch_attention_axis(
            metrics,
            reference,
            "miss_avoidance_fraction",
            "slot_count",
        ),
        "confusions": _koch_attention_axis(
            metrics,
            reference,
            "confusion_avoidance_fraction",
            "slot_count",
        ),
        "overall": _koch_attention_axis(
            metrics,
            reference,
            "overall_fraction",
            "exercise_count",
        ),
    }
    st_range = _format_st_range(rows)
    return {
        "key": key,
        "label": label,
        "st_range": st_range,
        "confidence": confidence,
        "exercise_count": len(rows),
        "reference_count": len(reference_rows),
        "axes": axes,
        "metrics": metrics,
        "reference_metrics": reference,
        "evidence": [
            _recognition_attention_evidence(label, st_range, metrics, rows, reference_rows),
        ],
    }


def _koch_attention_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    symbol_correct = sum(int(row["symbol_correct"]) for row in rows)
    symbol_available = sum(int(row["symbol_available"]) for row in rows)
    spacing_correct = sum(int(row["spacing_correct"]) for row in rows)
    spacing_available = sum(int(row["spacing_available"]) for row in rows)
    fractions = [float(row["combined_fraction"]) for row in rows]
    unit_length_fractions = [
        float(row["combined_fraction"]) for row in rows if int(row["burden_band"]) >= 3
    ]
    return {
        "exercise_count": len(rows),
        "symbol_fraction": (
            _round_or_none(_fraction(symbol_correct, symbol_available))
            if symbol_available
            else None
        ),
        "grouping_fraction": (
            _round_or_none(_fraction(spacing_correct, spacing_available))
            if spacing_available
            else None
        ),
        "unit_length_fraction": (
            _round_or_none(sum(unit_length_fractions) / len(unit_length_fractions))
            if unit_length_fractions
            else None
        ),
        "unit_length_exercise_count": len(unit_length_fractions),
        "overall_fraction": _round_or_none(sum(fractions) / len(fractions)) if fractions else None,
        "symbol_correct_units": symbol_correct,
        "symbol_available_units": symbol_available,
        "spacing_correct_units": spacing_correct,
        "spacing_available_units": spacing_available,
        "perfect_exercises": sum(1 for row in rows if float(row["combined_fraction"]) == 1.0),
    }


def _recognition_attention_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    slot_count = sum(int(row["slot_count"]) for row in rows)
    correct = sum(int(row["correct"]) for row in rows)
    substitutions = sum(int(row["substitutions"]) for row in rows)
    misses = sum(int(row["misses"]) for row in rows)
    fractions = [float(row["combined_fraction"]) for row in rows]
    return {
        "exercise_count": len(rows),
        "slot_count": slot_count,
        "accuracy_fraction": _round_or_none(_fraction(correct, slot_count)) if slot_count else None,
        "miss_avoidance_fraction": (
            _round_or_none(_fraction(slot_count - misses, slot_count)) if slot_count else None
        ),
        "confusion_avoidance_fraction": (
            _round_or_none(_fraction(slot_count - substitutions, slot_count))
            if slot_count
            else None
        ),
        "overall_fraction": _round_or_none(sum(fractions) / len(fractions)) if fractions else None,
        "correct_units": correct,
        "substitution_units": substitutions,
        "miss_units": misses,
    }


def _koch_attention_axis(
    metrics: dict[str, Any],
    reference: dict[str, Any],
    metric_key: str,
    count_key: str,
) -> dict[str, Any]:
    value = metrics.get(metric_key)
    reference_value = reference.get(metric_key)
    count = _coerce_int(metrics.get(count_key), 0)
    reference_count = _coerce_int(reference.get(count_key), 0)
    if (
        value is None
        or reference_value is None
        or count < ATTENTION_MIN_EXERCISES_PER_CONDITION
        or reference_count < ATTENTION_MIN_EXERCISES_PER_CONDITION
    ):
        return {
            "response": "unknown",
            "value": value,
            "reference": reference_value,
            "delta": None,
        }

    delta = float(value) - float(reference_value)
    if delta >= ATTENTION_HELPED_DELTA:
        response = "helped"
    elif delta <= -ATTENTION_HELPED_DELTA:
        response = "hurt"
    elif abs(delta) <= ATTENTION_NEUTRAL_DELTA:
        response = "neutral"
    else:
        response = "mixed"
    return {
        "response": response,
        "value": value,
        "reference": reference_value,
        "delta": round(delta, 6),
    }


def _format_st_range(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "not observed"
    s_values = [int(row["s"]) for row in rows]
    t_values = [int(row["t"]) for row in rows]
    return f"{_format_prefixed_range('S', s_values)} / {_format_prefixed_range('T', t_values)}"


def _format_prefixed_range(prefix: str, values: list[int]) -> str:
    if not values:
        return f"{prefix}?"
    low = min(values)
    high = max(values)
    if low == high:
        return f"{prefix}{low}"
    return f"{prefix}{low}-{prefix}{high}"


def _koch_attention_evidence(
    label: str,
    st_range: str,
    metrics: dict[str, Any],
    rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
) -> str:
    if not rows:
        return f"{label}: no saved Koch exercises with per-exercise S/T evidence."
    overall = metrics.get("overall_fraction")
    percent = _percent(float(overall)) if isinstance(overall, (int, float)) else "unknown"
    return (
        f"{label} ({st_range}) averaged {percent} over {len(rows)} exercises, "
        f"compared with {len(reference_rows)} exercises in the opposite S condition."
    )


def _recognition_attention_evidence(
    label: str,
    st_range: str,
    metrics: dict[str, Any],
    rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
) -> str:
    if not rows:
        return f"{label}: no saved recognition exercises with per-exercise S/T evidence."
    overall = metrics.get("overall_fraction")
    percent = _percent(float(overall)) if isinstance(overall, (int, float)) else "unknown"
    return (
        f"{label} ({st_range}) averaged {percent} over {len(rows)} exercises, "
        f"compared with {len(reference_rows)} exercises in the opposite S condition."
    )


def _recognition_listening_conditions_burden(rows: list[dict[str, Any]]) -> dict[str, Any]:
    default = [row for row in rows if row["condition"] == LISTENING_CONDITION_DEFAULT]
    textured = [row for row in rows if row["condition"] == LISTENING_CONDITION_TEXTURED]
    if not default or not textured:
        return _unknown_burden("No controlled default-vs-textured recognition probe yet.")

    default_metrics = _recognition_attention_metrics(default)
    textured_metrics = _recognition_attention_metrics(textured)
    default_overall = default_metrics.get("overall_fraction")
    textured_overall = textured_metrics.get("overall_fraction")
    confidence = _confidence_from_count(
        min(len(default), len(textured)),
        medium=LISTENING_MIN_EXERCISES_PER_CONDITION,
        high=ATTENTION_MIN_EXERCISES_PER_CONDITION,
    )

    if (
        default_overall is None
        or textured_overall is None
        or len(default) < LISTENING_MIN_EXERCISES_PER_CONDITION
        or len(textured) < LISTENING_MIN_EXERCISES_PER_CONDITION
    ):
        return {
            "debt": DEBT_UNKNOWN,
            "confidence": confidence,
            "evidence": [
                (
                    "Listening-condition probe needs at least "
                    f"{LISTENING_MIN_EXERCISES_PER_CONDITION} default and "
                    f"{LISTENING_MIN_EXERCISES_PER_CONDITION} textured exercises."
                )
            ],
            "default": default_metrics,
            "textured": textured_metrics,
        }

    delta = float(textured_overall) - float(default_overall)
    magnitude = abs(delta)
    if magnitude >= LISTENING_HIGH_DELTA:
        debt = DEBT_HIGH
    elif magnitude >= LISTENING_MODERATE_DELTA:
        debt = DEBT_MODERATE
    else:
        debt = DEBT_LOW

    if delta >= LISTENING_MODERATE_DELTA:
        response = "texture_helped"
        summary = "More textured signal performed better than the default signal"
    elif delta <= -LISTENING_MODERATE_DELTA:
        response = "texture_hurt"
        summary = "More textured signal performed worse than the default signal"
    else:
        response = "neutral"
        summary = "Default and more textured signal performance were similar"

    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": [
            (
                f"{summary}: {_percent(float(textured_overall))} over {len(textured)} "
                f"textured exercises vs {_percent(float(default_overall))} over "
                f"{len(default)} default exercises."
            )
        ],
        "response": response,
        "delta": round(delta, 6),
        "default": default_metrics,
        "textured": textured_metrics,
    }


def _koch_listening_conditions_burden(rows: list[dict[str, Any]]) -> dict[str, Any]:
    challenge = [row for row in rows if row.get("probe_phase") == KOCH_PROBE_PHASE_CHALLENGE]
    if challenge:
        metrics = _koch_attention_metrics(challenge)
        overall = metrics.get("overall_fraction")
        confidence = _confidence_from_count(
            len(challenge),
            medium=LISTENING_MIN_EXERCISES_PER_CONDITION,
            high=ATTENTION_MIN_EXERCISES_PER_CONDITION,
        )
        if overall is None or len(challenge) < LISTENING_MIN_EXERCISES_PER_CONDITION:
            return {
                "debt": DEBT_UNKNOWN,
                "confidence": confidence,
                "response": "needs_more_challenge_evidence",
                "evidence": [
                    (
                        "Koch listening challenge needs at least "
                        f"{LISTENING_MIN_EXERCISES_PER_CONDITION} saved challenge exercises."
                    )
                ],
                "challenge": metrics,
            }
        if float(overall) >= 0.90:
            debt = DEBT_LOW
            response = "challenge_stable"
        elif float(overall) >= 0.75:
            debt = DEBT_MODERATE
            response = "challenge_mixed"
        else:
            debt = DEBT_HIGH
            response = "challenge_hurt"
        return {
            "debt": debt,
            "confidence": confidence,
            "response": response,
            "evidence": [
                (
                    "Tougher Koch listening challenge: copied "
                    f"{_percent(float(overall))} over {len(challenge)} exercises."
                )
            ],
            "challenge": metrics,
        }

    default = [row for row in rows if row["condition"] == LISTENING_CONDITION_DEFAULT]
    textured = [row for row in rows if row["condition"] == LISTENING_CONDITION_TEXTURED]
    if not default or not textured:
        return _unknown_burden("No saved Koch listening challenge evidence yet.")

    default_metrics = _koch_attention_metrics(default)
    textured_metrics = _koch_attention_metrics(textured)
    default_overall = default_metrics.get("overall_fraction")
    textured_overall = textured_metrics.get("overall_fraction")
    confidence = _confidence_from_count(
        min(len(default), len(textured)),
        medium=LISTENING_MIN_EXERCISES_PER_CONDITION,
        high=ATTENTION_MIN_EXERCISES_PER_CONDITION,
    )

    if (
        default_overall is None
        or textured_overall is None
        or len(default) < LISTENING_MIN_EXERCISES_PER_CONDITION
        or len(textured) < LISTENING_MIN_EXERCISES_PER_CONDITION
    ):
        return {
            "debt": DEBT_UNKNOWN,
            "confidence": confidence,
            "evidence": [
                (
                    "Koch listening-condition probe needs at least "
                    f"{LISTENING_MIN_EXERCISES_PER_CONDITION} default and "
                    f"{LISTENING_MIN_EXERCISES_PER_CONDITION} textured exercises."
                )
            ],
            "default": default_metrics,
            "textured": textured_metrics,
        }

    delta = float(textured_overall) - float(default_overall)
    magnitude = abs(delta)
    if magnitude >= LISTENING_HIGH_DELTA:
        debt = DEBT_HIGH
    elif magnitude >= LISTENING_MODERATE_DELTA:
        debt = DEBT_MODERATE
    else:
        debt = DEBT_LOW

    if delta >= LISTENING_MODERATE_DELTA:
        response = "texture_helped"
        summary = "More textured Koch listening performed better than the default signal"
    elif delta <= -LISTENING_MODERATE_DELTA:
        response = "texture_hurt"
        summary = "More textured Koch listening performed worse than the default signal"
    else:
        response = "neutral"
        summary = "Default and more textured Koch listening performed similarly"

    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": [
            (
                f"{summary}: {_percent(float(textured_overall))} over {len(textured)} "
                f"textured exercises vs {_percent(float(default_overall))} over "
                f"{len(default)} default exercises."
            )
        ],
        "response": response,
        "delta": round(delta, 6),
        "default": default_metrics,
        "textured": textured_metrics,
    }


def _recognition_rhythm_burden(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = [row for row in rows if row["condition"] == "baseline"]
    probe = [row for row in rows if row["condition"] == "probe"]
    if not rows:
        return _unknown_burden("No saved recognition rhythm evidence yet.")
    baseline_metrics = _recognition_attention_metrics(baseline)
    if not probe:
        cadence_levels = sorted({int(row["cadence_variation"]) for row in baseline})
        level_text = (
            ", ".join(str(level) for level in cadence_levels) if cadence_levels else "unknown"
        )
        overall = baseline_metrics.get("overall_fraction")
        percent = _percent(float(overall)) if isinstance(overall, (int, float)) else "unknown"
        return {
            "debt": DEBT_UNKNOWN,
            "confidence": _confidence_from_count(
                len(baseline),
                medium=RHYTHM_MIN_EXERCISES_PER_CONDITION,
                high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
            ),
            "response": "baseline_observed",
            "evidence": [
                (
                    f"Stable rhythm baseline observed at cadence variation {level_text}: "
                    f"{percent} over {len(baseline)} exercises. Higher rhythm variation "
                    "has not been probed yet."
                )
            ],
            "baseline": baseline_metrics,
            "probe": _recognition_attention_metrics([]),
        }

    probe_metrics = _recognition_attention_metrics(probe)
    baseline_overall = baseline_metrics.get("overall_fraction")
    probe_overall = probe_metrics.get("overall_fraction")
    confidence = _confidence_from_count(
        min(len(baseline), len(probe)),
        medium=RHYTHM_MIN_EXERCISES_PER_CONDITION,
        high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
    )

    if (
        baseline_overall is None
        or probe_overall is None
        or len(baseline) < RHYTHM_MIN_EXERCISES_PER_CONDITION
        or len(probe) < RHYTHM_MIN_EXERCISES_PER_CONDITION
    ):
        return {
            "debt": DEBT_UNKNOWN,
            "confidence": confidence,
            "response": "needs_more_probe_evidence",
            "evidence": [
                (
                    "Rhythm probe needs at least "
                    f"{RHYTHM_MIN_EXERCISES_PER_CONDITION} baseline and "
                    f"{RHYTHM_MIN_EXERCISES_PER_CONDITION} raised-cadence exercises."
                )
            ],
            "baseline": baseline_metrics,
            "probe": probe_metrics,
        }

    delta = float(probe_overall) - float(baseline_overall)
    if delta <= -RHYTHM_HIGH_DELTA:
        debt = DEBT_HIGH
    elif delta <= -RHYTHM_MODERATE_DELTA:
        debt = DEBT_MODERATE
    else:
        debt = DEBT_LOW

    if delta <= -RHYTHM_MODERATE_DELTA:
        response = "rhythm_hurt"
        summary = "Raised rhythm variation performed worse than baseline"
    elif delta >= RHYTHM_MODERATE_DELTA:
        response = "rhythm_helped"
        summary = "Raised rhythm variation performed better than baseline"
    else:
        response = "neutral"
        summary = "Baseline and raised rhythm variation performance were similar"

    probe_levels = sorted({int(row["cadence_variation"]) for row in probe})
    baseline_levels = sorted({int(row["cadence_variation"]) for row in baseline})
    probe_text = ", ".join(str(level) for level in probe_levels) or "unknown"
    baseline_text = ", ".join(str(level) for level in baseline_levels) or "unknown"
    return {
        "debt": debt,
        "confidence": confidence,
        "response": response,
        "delta": round(delta, 6),
        "evidence": [
            (
                f"{summary}: {_percent(float(probe_overall))} over {len(probe)} "
                f"raised-cadence exercises (variation {probe_text}) vs "
                f"{_percent(float(baseline_overall))} over {len(baseline)} "
                f"baseline exercises (variation {baseline_text})."
            )
        ],
        "baseline": baseline_metrics,
        "probe": probe_metrics,
    }


def _koch_symbol_inventory_burden(
    stats: dict[str, Any],
    *,
    lifetime_stats: dict[str, Any],
    symbol_stats: dict[str, Any],
    recent_symbol_stats: dict[str, Any],
) -> dict[str, Any]:
    total = int(stats["symbol_available"])
    if total <= 0:
        return _unknown_burden("No Koch symbol-copy evidence in the recent window.")

    correct = int(stats["symbol_correct"])
    fraction = _fraction(correct, total)
    symbol_rows = _symbol_rows_from_stats(
        symbol_stats,
        recent_symbol_stats,
        sort_key=_symbol_sort_key,
    )
    lifetime_total = int(lifetime_stats["symbol_available"])
    lifetime_correct = int(lifetime_stats["symbol_correct"])
    lifetime_fraction = _fraction(lifetime_correct, lifetime_total)
    evidence = [
        f"Recent Koch sessions: copied symbols were correct {_percent(fraction)} of the time.",
        (
            f"Based on {total} copied symbols across "
            f"{_count_label(int(stats['exercise_count']), 'recent exercise')}."
        ),
    ]
    if lifetime_total > 0:
        evidence.extend(
            [
                (
                    "Since this symbol set began: copied symbols are correct "
                    f"{_percent(lifetime_fraction)} of the time."
                ),
                (
                    f"Based on {lifetime_total} copied symbols across "
                    f"{_count_label(int(lifetime_stats['exercise_count']), 'saved exercise')}."
                ),
            ]
        )
    evidence.extend(_symbol_inventory_evidence(symbol_rows, context="Koch"))
    return {
        "debt": _debt_from_fraction(fraction),
        "confidence": _confidence_from_count(
            total,
            medium=MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE,
            high=MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE,
        ),
        "evidence": evidence,
        "symbol_correct_units": correct,
        "symbol_available_units": total,
        "fraction": round(fraction, 6),
        "lifetime_symbol_correct_units": lifetime_correct,
        "lifetime_symbol_available_units": lifetime_total,
        "lifetime_fraction": round(lifetime_fraction, 6),
        "symbols": symbol_rows,
    }


def _koch_grouping_burden(
    stats: dict[str, Any],
    *,
    lifetime_stats: dict[str, Any],
) -> dict[str, Any]:
    total = int(stats["spacing_available"])
    if total <= 0:
        return _unknown_burden("No recent Koch exercises with word breaks to measure yet.")

    correct = int(stats["spacing_correct"])
    fraction = _fraction(correct, total)
    lifetime_total = int(lifetime_stats["spacing_available"])
    lifetime_correct = int(lifetime_stats["spacing_correct"])
    lifetime_fraction = _fraction(lifetime_correct, lifetime_total)
    evidence = [
        f"Recent Koch sessions: word breaks were correct {_percent(fraction)} of the time.",
        f"Based on {total} word breaks across recent Koch sessions.",
    ]
    if lifetime_total > 0:
        evidence.extend(
            [
                (
                    "Since this symbol set began: word breaks are correct "
                    f"{_percent(lifetime_fraction)} of the time."
                ),
                f"Based on {lifetime_total} word breaks across all saved Koch sessions.",
            ]
        )
    return {
        "debt": _debt_from_fraction(fraction),
        "confidence": _confidence_from_count(
            total,
            medium=MIN_UNIT_EXERCISES_MEDIUM_CONFIDENCE,
            high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
        ),
        "evidence": evidence,
        "spacing_correct_units": correct,
        "spacing_available_units": total,
        "fraction": round(fraction, 6),
        "lifetime_spacing_correct_units": lifetime_correct,
        "lifetime_spacing_available_units": lifetime_total,
        "lifetime_fraction": round(lifetime_fraction, 6),
    }


def _koch_unit_length_burden(
    stats: dict[str, Any],
    *,
    lifetime_stats: dict[str, Any],
) -> dict[str, Any]:
    band_attempts: dict[int, list[tuple[float, int]]] = stats["band_attempts"]
    if not band_attempts:
        return _unknown_burden("No Koch band evidence in the recent window.")

    rows = []
    for band, entries in sorted(band_attempts.items()):
        fractions = [fraction for fraction, _gear in entries]
        average = sum(fractions) / len(fractions)
        rows.append(
            {
                "band": band,
                "average_fraction": average,
                "exercise_count": len(entries),
                "current_gear": entries[0][1],
            }
        )
    weakest = min(rows, key=lambda row: (row["average_fraction"], -row["band"]))
    all_fractions = [fraction for entries in band_attempts.values() for fraction, _gear in entries]
    average = sum(all_fractions) / len(all_fractions)
    lifetime_attempts: dict[int, list[tuple[float, int]]] = lifetime_stats["band_attempts"]
    lifetime_fractions = [
        fraction for entries in lifetime_attempts.values() for fraction, _gear in entries
    ]
    lifetime_average = (
        sum(lifetime_fractions) / len(lifetime_fractions) if lifetime_fractions else 0.0
    )
    evidence = [
        (
            f"Recent Koch sessions: band {weakest['band']} at gear {weakest['current_gear']} "
            f"is the current weak spot, averaging {_percent(float(weakest['average_fraction']))}."
        ),
        (
            f"Based on {_count_label(weakest['exercise_count'], 'recent exercise')} "
            f"at gear {weakest['current_gear']}."
        ),
        (
            "Recent Koch sessions: all exercise groups average "
            f"{_percent(average)} across {_count_label(len(all_fractions), 'exercise')}."
        ),
    ]
    if lifetime_fractions:
        evidence.append(
            "Since this symbol set began: all exercise groups average "
            f"{_percent(lifetime_average)} across "
            f"{_count_label(len(lifetime_fractions), 'saved exercise')}."
        )

    return {
        "debt": _debt_from_fraction(float(weakest["average_fraction"])),
        "confidence": _confidence_from_count(
            len(all_fractions),
            medium=MIN_UNIT_EXERCISES_MEDIUM_CONFIDENCE,
            high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
        ),
        "evidence": evidence,
        "bands": [
            {
                **row,
                "average_fraction": round(float(row["average_fraction"]), 6),
            }
            for row in rows
        ],
        "average_fraction": round(average, 6),
        "lifetime_average_fraction": round(lifetime_average, 6),
        "lifetime_exercise_count": len(lifetime_fractions),
    }


def _koch_confusion_burden(confusions: dict[str, Any]) -> dict[str, Any]:
    substitutions = confusions.get("substitutions")
    pairs = substitutions if isinstance(substitutions, list) else []
    exercises_used = _coerce_int(confusions.get("exercises_used"), 0)
    if exercises_used <= 0:
        return _unknown_burden("No saved Koch answers available for confusion evidence.")

    confidence = _confidence_from_count(
        exercises_used,
        medium=MIN_UNIT_EXERCISES_MEDIUM_CONFIDENCE,
        high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
    )
    if not pairs:
        return {
            "debt": DEBT_LOW,
            "confidence": confidence,
            "evidence": [f"No Koch symbol substitutions across {exercises_used} exercises."],
            "committed": [],
        }

    top = pairs[0]
    top_count = _coerce_int(top.get("count") if isinstance(top, dict) else None, 0)
    if top_count >= HIGH_CONFUSION_COUNT:
        debt = DEBT_HIGH
    elif top_count >= MODERATE_CONFUSION_COUNT:
        debt = DEBT_MODERATE
    else:
        debt = DEBT_LOW

    target = top.get("target", "?") if isinstance(top, dict) else "?"
    typed = top.get("typed", "?") if isinstance(top, dict) else "?"
    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": [f"Top Koch symbol confusion {target} -> {typed} occurred {top_count} times."],
        "committed": pairs,
    }


def _collect_symbol_stats(
    records: list[dict[str, Any]],
    *,
    symbols: set[str],
) -> dict[str, Any]:
    symbol_slots: dict[str, Counter[str]] = defaultdict(Counter)
    introduced_at: dict[str, str] = {}

    for record in sorted(
        _recognition_records(records), key=lambda r: str(r.get("started_at") or "")
    ):
        started_at = str(record.get("started_at") or "")
        exercises = record.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("has_evidence") is not True:
                continue

            slots = analysis.get("slots")
            if not isinstance(slots, list):
                continue
            for slot in slots:
                if not isinstance(slot, dict):
                    continue
                truth = slot.get("truth")
                outcome = slot.get("outcome")
                if not isinstance(truth, str) or not truth or not isinstance(outcome, str):
                    continue
                symbol = truth.upper()
                if symbols and symbol not in symbols:
                    continue
                symbol_slots[symbol][outcome] += 1
                introduced_at.setdefault(symbol, started_at)

    return {
        "symbol_slots": symbol_slots,
        "introduced_at": introduced_at,
    }


def _symbol_sort_key(symbol: str) -> tuple[int, str]:
    try:
        return (patterns.KOCH_ORDER.index(symbol), symbol)
    except ValueError:
        return (len(patterns.KOCH_ORDER), symbol)


def _symbol_rows_from_stats(
    stats: dict[str, Any],
    recent_stats: dict[str, Any],
    *,
    sort_key: Any = None,
) -> list[dict[str, Any]]:
    symbol_slots: dict[str, Counter[str]] = stats["symbol_slots"]
    recent_symbol_slots: dict[str, Counter[str]] = recent_stats["symbol_slots"]
    introduced_at: dict[str, str] = stats["introduced_at"]
    rows = []
    for symbol in sorted(symbol_slots, key=sort_key):
        counts = symbol_slots[symbol]
        total = sum(counts.values())
        correct = counts["correct"] + counts["caught_correct"]
        recent_counts = recent_symbol_slots.get(symbol, Counter())
        recent_total = sum(recent_counts.values())
        recent_correct = recent_counts["correct"] + recent_counts["caught_correct"]
        rows.append(
            {
                "symbol": symbol,
                "introduced_at": introduced_at.get(symbol, ""),
                "exposures": total,
                "correct": correct,
                "fraction": _fraction(correct, total),
                "misses": counts["miss"],
                "substitutions": counts["substitution"] + counts["caught_substitution"],
                "lifetime_exposures": total,
                "lifetime_correct": correct,
                "lifetime_fraction": _fraction(correct, total),
                "lifetime_misses": counts["miss"],
                "lifetime_substitutions": counts["substitution"] + counts["caught_substitution"],
                "recent_exposures": recent_total,
                "recent_correct": recent_correct,
                "recent_fraction": _fraction(recent_correct, recent_total),
                "recent_misses": recent_counts["miss"],
                "recent_substitutions": recent_counts["substitution"]
                + recent_counts["caught_substitution"],
            }
        )

    for row in rows:
        row["signal"] = _symbol_signal(row)
    return rows


def _symbol_inventory_evidence(rows: list[dict[str, Any]], *, context: str) -> list[str]:
    if not rows:
        return []

    evidence = []
    prefix = f"{context} " if context else ""
    weakest = min(rows, key=lambda row: (row["lifetime_fraction"], row["lifetime_exposures"]))
    evidence.append(
        (
            f"Weakest lifetime {prefix}symbol {weakest['symbol']} at "
            f"{_percent(weakest['lifetime_fraction'])} over "
            f"{weakest['lifetime_exposures']} exposures since introduction."
        )
    )
    weakest_recent = min(
        [row for row in rows if row["recent_exposures"] > 0],
        key=lambda row: (row["recent_fraction"], row["recent_exposures"]),
        default=None,
    )
    if weakest_recent:
        evidence.append(
            f"Weakest recent {prefix}symbol {weakest_recent['symbol']} at "
            f"{_percent(weakest_recent['recent_fraction'])} over "
            f"{weakest_recent['recent_exposures']} exposures in the recent window."
        )
    stable = [row["symbol"] for row in rows if row["lifetime_fraction"] >= STRONG_FRACTION]
    if stable:
        evidence.append(
            f"Stable lifetime {prefix}symbols at current evidence threshold: "
            f"{' '.join(stable)}."
        )
    return evidence


def _symbol_inventory_burden(
    stats: dict[str, Any],
    recent_stats: dict[str, Any],
) -> dict[str, Any]:
    if not stats["symbol_slots"]:
        return _unknown_burden("No symbol-level recognition slots available.")

    rows = _symbol_rows_from_stats(stats, recent_stats)
    weakest = min(rows, key=lambda row: (row["lifetime_fraction"], row["lifetime_exposures"]))
    min_exposures = min(row["lifetime_exposures"] for row in rows)
    confidence = _confidence_from_count(
        min_exposures,
        medium=MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE,
        high=MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE,
    )
    debt = _debt_from_fraction(weakest["lifetime_fraction"])
    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": _symbol_inventory_evidence(rows, context=""),
        "symbols": rows,
    }


def _symbol_signal(row: dict[str, Any]) -> str:
    lifetime_exposures = int(row["lifetime_exposures"])
    recent_exposures = int(row["recent_exposures"])
    lifetime_fraction = float(row["lifetime_fraction"])
    recent_fraction = float(row["recent_fraction"])

    if lifetime_exposures < MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE:
        return "undersampled"
    if recent_exposures < MIN_SYMBOL_RECENT_EXPOSURES_SIGNAL:
        return "watch"
    if lifetime_fraction >= STRONG_FRACTION and recent_fraction >= STRONG_FRACTION:
        return "stable"
    if lifetime_fraction < STRONG_FRACTION and recent_fraction >= STRONG_FRACTION:
        return "recovering"
    if lifetime_fraction < STRONG_FRACTION and recent_fraction < LOW_FRACTION:
        return "fragile"
    return "watch"


def _recognition_estimated_time(
    records: list[dict[str, Any]],
    *,
    claimed_set_key: str,
    symbol_inventory: dict[str, Any],
    window_size: int,
) -> dict[str, Any]:
    sessions = [_recognition_session_summary(record) for record in records]
    sessions = [session for session in sessions if session["total"] > 0]
    sessions.sort(key=lambda session: session["started_at"])
    recent = sessions[-window_size:] if window_size > 0 else []
    pace_source = recent or sessions

    correct = sum(session["correct"] for session in sessions)
    total = sum(session["total"] for session in sessions)
    practice_seconds = round(sum(session["duration_seconds"] for session in sessions), 3)
    seconds_per_session = _average(
        [session["duration_seconds"] for session in pace_source if session["duration_seconds"] > 0]
    )
    slots_per_session = _average([session["total"] for session in pace_source])
    recent_correct = sum(session["correct"] for session in recent)
    recent_total = sum(session["total"] for session in recent)
    recent_fraction = _fraction(recent_correct, recent_total)

    symbols = symbol_inventory.get("symbols") if isinstance(symbol_inventory, dict) else []
    symbol_rows = [row for row in symbols if isinstance(row, dict)]
    symbol_count = max(1, len(symbol_rows))
    fallback_symbol_slots = (slots_per_session or 0.0) / symbol_count

    return {
        "version": ESTIMATED_TIME_VERSION,
        "next_symbol": patterns.next_koch_after(str(symbol) for symbol in claimed_set_key.split()),
        "target_fraction": RECOGNITION_TARGET_FRACTION,
        "current": {
            "sessions": len(sessions),
            "practice_seconds": practice_seconds,
            "correct": correct,
            "total": total,
            "fraction": _round_or_none(_fraction(correct, total)),
        },
        "pace": {
            "window_sessions": len(pace_source),
            "seconds_per_session": _round_or_none(seconds_per_session),
            "slots_per_session": _round_or_none(slots_per_session),
            "recent_fraction": _round_or_none(recent_fraction),
        },
        "estimates": [
            _estimate_slots_goal(
                "aggregate_90_recent",
                "Aggregate Recognition to 90%",
                correct=correct,
                total=total,
                future_accuracy=recent_fraction,
                slots_per_session=slots_per_session,
                seconds_per_session=seconds_per_session,
                practice_seconds=practice_seconds,
            ),
            _estimate_slots_goal(
                "aggregate_90_best",
                "Aggregate Recognition to 90% - perfect floor",
                correct=correct,
                total=total,
                future_accuracy=1.0,
                slots_per_session=slots_per_session,
                seconds_per_session=seconds_per_session,
                practice_seconds=practice_seconds,
            ),
            _estimate_claimed_symbols_goal(
                "claimed_symbols_90_best",
                "Claimed symbols all 90% - perfect floor",
                symbol_rows=symbol_rows,
                future_accuracy=1.0,
                pace_window_sessions=len(pace_source),
                fallback_symbol_slots_per_session=fallback_symbol_slots,
                seconds_per_session=seconds_per_session,
                practice_seconds=practice_seconds,
            ),
            _estimate_claimed_symbols_range(
                symbol_rows=symbol_rows,
                pace_window_sessions=len(pace_source),
                fallback_symbol_slots_per_session=fallback_symbol_slots,
                seconds_per_session=seconds_per_session,
                practice_seconds=practice_seconds,
            ),
        ],
    }


def _recognition_session_summary(record: dict[str, Any]) -> dict[str, Any]:
    correct = 0
    total = 0
    exercises = record.get("exercises")
    if isinstance(exercises, list):
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            analysis = exercise.get("analysis")
            if not isinstance(analysis, dict) or analysis.get("has_evidence") is not True:
                continue
            slots = analysis.get("slots")
            if not isinstance(slots, list):
                continue
            for slot in slots:
                if not isinstance(slot, dict) or not slot.get("truth"):
                    continue
                outcome = slot.get("outcome")
                total += 1
                if outcome in {"correct", "caught_correct"}:
                    correct += 1
    return {
        "started_at": str(record.get("started_at") or ""),
        "duration_seconds": _record_duration_seconds(record),
        "correct": correct,
        "total": total,
    }


def _record_duration_seconds(record: dict[str, Any]) -> float:
    started = _parse_record_datetime(record.get("started_at"))
    ended = _parse_record_datetime(record.get("ended_at"))
    if started is None or ended is None:
        return 0.0
    seconds = (ended - started).total_seconds()
    if seconds <= 0 or seconds > 3600:
        return 0.0
    return seconds


def _parse_record_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _estimate_slots_goal(
    key: str,
    label: str,
    *,
    correct: int,
    total: int,
    future_accuracy: float,
    slots_per_session: float,
    seconds_per_session: float,
    practice_seconds: float,
) -> dict[str, Any]:
    slots_needed = _future_slots_needed(
        correct=correct,
        total=total,
        target=RECOGNITION_TARGET_FRACTION,
        future_accuracy=future_accuracy,
    )
    return _estimate_from_slots(
        key,
        label,
        slots_needed=slots_needed,
        future_accuracy=future_accuracy,
        slots_per_session=slots_per_session,
        seconds_per_session=seconds_per_session,
        practice_seconds=practice_seconds,
    )


def _estimate_claimed_symbols_goal(
    key: str,
    label: str,
    *,
    symbol_rows: list[dict[str, Any]],
    future_accuracy: float,
    pace_window_sessions: int,
    fallback_symbol_slots_per_session: float,
    seconds_per_session: float,
    practice_seconds: float,
) -> dict[str, Any]:
    sessions_needed = 0
    blocking_symbol = None
    for row in symbol_rows:
        slots_needed = _future_slots_needed(
            correct=_coerce_int(row.get("lifetime_correct"), 0),
            total=_coerce_int(row.get("lifetime_exposures"), 0),
            target=RECOGNITION_TARGET_FRACTION,
            future_accuracy=future_accuracy,
        )
        if slots_needed is None:
            return {
                "key": key,
                "label": label,
                "status": "not_trending",
                "future_accuracy": _round_or_none(future_accuracy),
                "blocking_symbol": row.get("symbol") or None,
            }
        symbol_slots_per_session = _number_like(row.get("recent_exposures")) / max(
            1, pace_window_sessions
        )
        if symbol_slots_per_session <= 0:
            symbol_slots_per_session = fallback_symbol_slots_per_session
        symbol_sessions = _sessions_from_slots(slots_needed, symbol_slots_per_session)
        if symbol_sessions > sessions_needed:
            sessions_needed = symbol_sessions
            blocking_symbol = row.get("symbol") or None

    return _estimate_from_sessions(
        key,
        label,
        sessions_needed=sessions_needed,
        future_accuracy=future_accuracy,
        seconds_per_session=seconds_per_session,
        practice_seconds=practice_seconds,
        blocking_symbol=blocking_symbol,
    )


def _estimate_claimed_symbols_range(
    *,
    symbol_rows: list[dict[str, Any]],
    pace_window_sessions: int,
    fallback_symbol_slots_per_session: float,
    seconds_per_session: float,
    practice_seconds: float,
) -> dict[str, Any]:
    low = _estimate_claimed_symbols_goal(
        "claimed_symbols_90_settled_low",
        "Claimed symbols all 90%",
        symbol_rows=symbol_rows,
        future_accuracy=SETTLED_FUTURE_ACCURACY_LOW,
        pace_window_sessions=pace_window_sessions,
        fallback_symbol_slots_per_session=fallback_symbol_slots_per_session,
        seconds_per_session=seconds_per_session,
        practice_seconds=practice_seconds,
    )
    high = _estimate_claimed_symbols_goal(
        "claimed_symbols_90_settled_high",
        "Claimed symbols all 90%",
        symbol_rows=symbol_rows,
        future_accuracy=SETTLED_FUTURE_ACCURACY_HIGH,
        pace_window_sessions=pace_window_sessions,
        fallback_symbol_slots_per_session=fallback_symbol_slots_per_session,
        seconds_per_session=seconds_per_session,
        practice_seconds=practice_seconds,
    )
    return {
        "key": "claimed_symbols_90_settled_range",
        "label": "Claimed symbols all 90%",
        "status": "estimated",
        "assumption": "future_accuracy_96_98",
        "future_accuracy_low": SETTLED_FUTURE_ACCURACY_LOW,
        "future_accuracy_high": SETTLED_FUTURE_ACCURACY_HIGH,
        "sessions_low": high.get("sessions"),
        "sessions_high": low.get("sessions"),
        "seconds_low": high.get("seconds"),
        "seconds_high": low.get("seconds"),
        "total_seconds_low": high.get("total_seconds"),
        "total_seconds_high": low.get("total_seconds"),
        "blocking_symbol": low.get("blocking_symbol") or high.get("blocking_symbol"),
    }


def _estimate_from_slots(
    key: str,
    label: str,
    *,
    slots_needed: int | None,
    future_accuracy: float,
    slots_per_session: float,
    seconds_per_session: float,
    practice_seconds: float,
) -> dict[str, Any]:
    if slots_needed is None:
        return {
            "key": key,
            "label": label,
            "status": "not_trending",
            "future_accuracy": _round_or_none(future_accuracy),
        }
    return _estimate_from_sessions(
        key,
        label,
        sessions_needed=_sessions_from_slots(slots_needed, slots_per_session),
        future_accuracy=future_accuracy,
        seconds_per_session=seconds_per_session,
        practice_seconds=practice_seconds,
    )


def _estimate_from_sessions(
    key: str,
    label: str,
    *,
    sessions_needed: int,
    future_accuracy: float,
    seconds_per_session: float,
    practice_seconds: float,
    blocking_symbol: Any = None,
) -> dict[str, Any]:
    seconds = round(max(0, sessions_needed) * max(0.0, seconds_per_session), 3)
    estimate = {
        "key": key,
        "label": label,
        "status": "already_met" if sessions_needed <= 0 else "estimated",
        "future_accuracy": _round_or_none(future_accuracy),
        "sessions": max(0, sessions_needed),
        "seconds": seconds,
        "total_seconds": round(practice_seconds + seconds, 3),
    }
    if blocking_symbol:
        estimate["blocking_symbol"] = blocking_symbol
    return estimate


def _future_slots_needed(
    *,
    correct: int,
    total: int,
    target: float,
    future_accuracy: float,
) -> int | None:
    if total <= 0:
        return 0
    if _fraction(correct, total) >= target:
        return 0
    if future_accuracy <= target:
        return None
    projected = ((target * total) - correct) / (future_accuracy - target)
    return max(0, ceil(projected - 1e-9))


def _sessions_from_slots(slots_needed: int, slots_per_session: float) -> int:
    if slots_needed <= 0:
        return 0
    if slots_per_session <= 0:
        return 0
    return ceil(slots_needed / slots_per_session)


def _average(values: list[float]) -> float:
    values = [float(value) for value in values if isinstance(value, (int, float))]
    if not values:
        return 0.0
    return sum(values) / len(values)


def _number_like(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _unit_length_burden(stats: dict[str, Any]) -> dict[str, Any]:
    unit_attempts: dict[int, list[float]] = stats["unit_attempts"]
    grouped = [
        fraction for gear, fractions in unit_attempts.items() if gear >= 1 for fraction in fractions
    ]
    if not grouped:
        return _unknown_burden("No pair or longer-unit recognition evidence yet.")

    average = sum(grouped) / len(grouped)
    debt = _debt_from_fraction(average)
    confidence = _confidence_from_count(
        len(grouped),
        medium=MIN_UNIT_EXERCISES_MEDIUM_CONFIDENCE,
        high=MIN_UNIT_EXERCISES_HIGH_CONFIDENCE,
    )
    evidence = [
        f"Grouped-unit recognition averaged {_percent(average)} " f"over {len(grouped)} exercises."
    ]
    singles = unit_attempts.get(0, [])
    if singles:
        single_average = sum(singles) / len(singles)
        evidence.append(
            f"Single-symbol recognition averaged {_percent(single_average)} "
            f"over {len(singles)} exercises."
        )

    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": evidence,
        "exercise_count": len(grouped),
        "average_fraction": round(average, 6),
    }


def _confusion_burden(stats: dict[str, Any]) -> dict[str, Any]:
    committed: Counter[tuple[str, str]] = stats["committed_confusions"]
    caught: Counter[tuple[str, str]] = stats["caught_confusions"]
    symbol_slots: dict[str, Counter[str]] = stats["symbol_slots"]
    exposures = sum(sum(counts.values()) for counts in symbol_slots.values())

    if exposures <= 0:
        return _unknown_burden("No recognition slots available for confusion evidence.")

    confidence = _confidence_from_count(
        exposures,
        medium=MIN_CONFUSION_EXPOSURES_MEDIUM_CONFIDENCE,
        high=MIN_CONFUSION_EXPOSURES_HIGH_CONFIDENCE,
    )
    if not committed:
        return {
            "debt": DEBT_LOW,
            "confidence": confidence,
            "evidence": [f"No committed confusions across {exposures} symbol exposures."],
            "committed": [],
            "caught": _format_pairs(caught),
        }

    top_pair, top_count = committed.most_common(1)[0]
    if top_count >= HIGH_CONFUSION_COUNT:
        debt = DEBT_HIGH
    elif top_count >= MODERATE_CONFUSION_COUNT:
        debt = DEBT_MODERATE
    else:
        debt = DEBT_LOW

    evidence = [
        f"Top committed confusion {top_pair[0]} -> {top_pair[1]} " f"occurred {top_count} times."
    ]
    if caught:
        caught_pair, caught_count = caught.most_common(1)[0]
        evidence.append(
            f"Top caught confusion {caught_pair[0]} -> {caught_pair[1]} "
            f"occurred {caught_count} times."
        )

    return {
        "debt": debt,
        "confidence": confidence,
        "evidence": evidence,
        "committed": _format_pairs(committed),
        "caught": _format_pairs(caught),
    }


def _unknown_burden(evidence: str) -> dict[str, Any]:
    return {
        "debt": DEBT_UNKNOWN,
        "confidence": CONFIDENCE_LOW,
        "evidence": [evidence],
    }


def _recognition_anchor_burden() -> dict[str, Any]:
    return {
        "debt": DEBT_UNKNOWN,
        "confidence": CONFIDENCE_HIGH,
        "response": "not_currently_used",
        "evidence": [
            (
                "Anchor is not currently active as a Recognition practice burden. "
                "The existing phonetic scaffold is limited to the early gear-0 flow."
            ),
            (
                "Later context streams can use structural anchors such as CQ, DE, "
                "callsigns, RST reports, Q-codes, and 73 to help orientation in "
                "longer copy."
            ),
        ],
    }


def _recognition_practice_transfer_burden(
    recognition_stats: dict[str, Any],
    koch_stats: dict[str, Any],
    *,
    koch_records_used: int,
) -> dict[str, Any]:
    recognition_metrics = _recognition_symbol_transfer_metrics(recognition_stats)
    koch_metrics = _koch_transfer_metrics(koch_stats)
    recognition_total = int(recognition_metrics["symbol_available_units"])
    koch_total = int(koch_metrics["symbol_available_units"])

    if recognition_total < TRANSFER_MIN_RECOGNITION_SLOTS:
        return {
            "debt": DEBT_UNKNOWN,
            "confidence": CONFIDENCE_LOW,
            "response": "needs_recognition_evidence",
            "evidence": [
                (
                    "Practice transfer needs recent Symbol Recognition evidence before "
                    "Koch Exercise copy can be interpreted as transfer."
                )
            ],
            "recognition": recognition_metrics,
            "koch": koch_metrics,
        }
    if koch_total < TRANSFER_MIN_KOCH_SYMBOL_UNITS:
        return {
            "debt": DEBT_UNKNOWN,
            "confidence": CONFIDENCE_LOW,
            "response": "needs_koch_evidence",
            "evidence": [
                (
                    "Practice transfer needs matching non-warm-up Koch Exercise evidence "
                    "for the current claimed set."
                )
            ],
            "recognition": recognition_metrics,
            "koch": koch_metrics,
            "koch_records_used": koch_records_used,
        }

    recognition_fraction = float(recognition_metrics["symbol_fraction"])
    koch_fraction = float(koch_metrics["symbol_fraction"])
    delta = koch_fraction - recognition_fraction
    weakest_band = koch_metrics.get("weakest_band")
    confidence = _confidence_from_count(
        min(recognition_total, koch_total),
        medium=MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE,
        high=MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE,
    )

    if koch_fraction < TRANSFER_HIGH_ABSOLUTE_FRACTION or delta <= -TRANSFER_HIGH_DELTA:
        debt = DEBT_HIGH
        response = "transfer_hurt"
        summary = "Koch Exercise copy is much weaker than recent Symbol Recognition"
    elif koch_fraction < TRANSFER_LOW_ABSOLUTE_FRACTION or delta <= -TRANSFER_MODERATE_DELTA:
        debt = DEBT_MODERATE
        response = "transfer_lag"
        summary = "Koch Exercise copy is lagging behind recent Symbol Recognition"
    else:
        debt = DEBT_LOW
        response = "transfer_stable"
        summary = "Recognition is carrying into Koch Exercises"

    evidence = [
        (
            f"{summary}: Koch symbol copy {_percent(koch_fraction)} over "
            f"{koch_total} symbol units vs Recognition {_percent(recognition_fraction)} "
            f"over {recognition_total} recent symbol slots."
        )
    ]
    if isinstance(weakest_band, dict):
        evidence.append(
            f"Weakest Koch burden band {weakest_band['band']} averaged "
            f"{_percent(float(weakest_band['average_fraction']))} over "
            f"{weakest_band['exercise_count']} exercises."
        )

    return {
        "debt": debt,
        "confidence": confidence,
        "response": response,
        "delta": round(delta, 6),
        "evidence": evidence,
        "recognition": recognition_metrics,
        "koch": koch_metrics,
        "koch_records_used": koch_records_used,
    }


def _recognition_symbol_transfer_metrics(stats: dict[str, Any]) -> dict[str, Any]:
    symbol_slots: dict[str, Counter[str]] = stats["symbol_slots"]
    correct = 0
    total = 0
    for counts in symbol_slots.values():
        total += sum(counts.values())
        correct += counts["correct"] + counts["caught_correct"]
    return {
        "symbol_correct_units": correct,
        "symbol_available_units": total,
        "symbol_fraction": _round_or_none(_fraction(correct, total)) if total else None,
    }


def _koch_transfer_metrics(stats: dict[str, Any]) -> dict[str, Any]:
    symbol_correct = int(stats["symbol_correct"])
    symbol_available = int(stats["symbol_available"])
    spacing_correct = int(stats["spacing_correct"])
    spacing_available = int(stats["spacing_available"])
    band_attempts: dict[int, list[tuple[float, int]]] = stats["band_attempts"]
    bands = []
    for band, entries in sorted(band_attempts.items()):
        fractions = [fraction for fraction, _gear in entries]
        bands.append(
            {
                "band": band,
                "average_fraction": round(sum(fractions) / len(fractions), 6),
                "exercise_count": len(entries),
            }
        )
    weakest_band = (
        min(bands, key=lambda row: (row["average_fraction"], -row["band"])) if bands else None
    )
    return {
        "exercise_count": int(stats["exercise_count"]),
        "symbol_correct_units": symbol_correct,
        "symbol_available_units": symbol_available,
        "symbol_fraction": (
            _round_or_none(_fraction(symbol_correct, symbol_available))
            if symbol_available
            else None
        ),
        "spacing_correct_units": spacing_correct,
        "spacing_available_units": spacing_available,
        "spacing_fraction": (
            _round_or_none(_fraction(spacing_correct, spacing_available))
            if spacing_available
            else None
        ),
        "bands": bands,
        "weakest_band": weakest_band,
    }


def _debt_from_fraction(value: float) -> str:
    if value >= STRONG_FRACTION:
        return DEBT_LOW
    if value >= LOW_FRACTION:
        return DEBT_MODERATE
    return DEBT_HIGH


def _confidence_from_count(count: int, *, medium: int, high: int) -> str:
    if count >= high:
        return CONFIDENCE_HIGH
    if count >= medium:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _tally_pair(counter: Counter[tuple[str, str]], pair: Any) -> None:
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return
    target, typed = pair
    if isinstance(target, str) and isinstance(typed, str):
        counter[(target.upper(), typed.upper())] += 1


def _format_pairs(counter: Counter[tuple[str, str]]) -> list[dict[str, Any]]:
    return [
        {"target": target, "typed": typed, "count": count}
        for (target, typed), count in counter.most_common()
    ]


def _record_gear(record: dict[str, Any]) -> int:
    generation = record.get("generation")
    if not isinstance(generation, dict):
        return 0
    return _coerce_int(generation.get("gear"), 0)


def _koch_gears_from_generation(generation: Any) -> dict[int, int]:
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
        gear = entry.get("gear")
        if (
            isinstance(idx, int)
            and not isinstance(idx, bool)
            and isinstance(gear, int)
            and not isinstance(gear, bool)
        ):
            out[idx] = gear
    return out


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _fraction(correct: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, correct / total))


def _percent(value: float) -> str:
    return f"{round(value * 100, 1)}%"


def _count_label(count: int, singular: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {singular}{suffix}"


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)
