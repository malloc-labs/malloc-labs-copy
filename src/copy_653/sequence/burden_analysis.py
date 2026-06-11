"""Burden-debt profile derivation for saved recognition evidence.

This module is read-only analysis. It interprets existing Symbol
Recognition records into backend evidence about burdens, debt, and
confidence; it does not change generation or learner-facing progression.
"""

from __future__ import annotations

from collections import Counter
from collections import defaultdict
from typing import Any

from copy_653.sequence.burden_attention import (
    load_koch_attention_response as load_koch_attention_response,
    load_recognition_attention_response as load_recognition_attention_response,
)
from copy_653.sequence.burden_estimates import recognition_estimated_time
from copy_653.sequence.burden_probes import (
    collect_koch_listening_probe_exercises,
    collect_recognition_listening_probe_exercises,
    collect_recognition_rhythm_exercises,
    koch_listening_conditions_burden,
    recognition_listening_conditions_burden,
    recognition_rhythm_burden,
)
from copy_653.sequence.burden_symbols import (
    collect_koch_symbol_stats,
    collect_symbol_stats,
    debt_from_fraction,
    koch_symbol_inventory_burden,
    matching_recognition_records,
    recognition_next_symbol_readiness as recognition_next_symbol_readiness,
    symbol_inventory_burden,
)
from copy_653.sequence.exercise_analysis import (
    DEFAULT_EVIDENCE_WINDOW_SIZE as DEFAULT_KOCH_BURDEN_WINDOW_SIZE,
    load_confusion_pairs,
    record_claimed_set_key,
)
from copy_653.sequence.recognition_analysis import recognition_review_analysis

BURDEN_PROFILE_VERSION = "burden-profile-v1"
DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE = 20
RECOGNITION_TARGET_FRACTION = 0.90
DEBT_LOW = "low"
DEBT_MODERATE = "moderate"
DEBT_HIGH = "high"
DEBT_UNKNOWN = "unknown"

CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

MIN_SYMBOL_EXPOSURES_MEDIUM_CONFIDENCE = 8
MIN_SYMBOL_EXPOSURES_HIGH_CONFIDENCE = 20
MIN_UNIT_EXERCISES_MEDIUM_CONFIDENCE = 4
MIN_UNIT_EXERCISES_HIGH_CONFIDENCE = 10
MIN_CONFUSION_EXPOSURES_MEDIUM_CONFIDENCE = 20
MIN_CONFUSION_EXPOSURES_HIGH_CONFIDENCE = 80

MODERATE_CONFUSION_COUNT = 2
HIGH_CONFUSION_COUNT = 4

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
    listening_probe_rows = collect_recognition_listening_probe_exercises(recent)
    rhythm_rows = collect_recognition_rhythm_exercises(recent)
    symbol_stats = collect_symbol_stats(records, symbols=claimed_symbols)
    recent_symbol_stats = collect_symbol_stats(recent, symbols=claimed_symbols)
    symbol_inventory = symbol_inventory_burden(symbol_stats, recent_symbol_stats)

    return {
        "version": BURDEN_PROFILE_VERSION,
        "claimed_set_key": claimed_set_key,
        "record_count": len(matching),
        "window_size": max(0, window_size),
        "records_used": len(recent),
        "estimated_time": recognition_estimated_time(
            matching,
            claimed_set_key=claimed_set_key,
            symbol_inventory=symbol_inventory,
            window_size=max(0, window_size),
        ),
        "burdens": {
            "symbol_inventory": symbol_inventory,
            "unit_length": _unit_length_burden(stats),
            "confusion": _confusion_burden(stats),
            "signal": recognition_listening_conditions_burden(listening_probe_rows),
            "rhythm": recognition_rhythm_burden(rhythm_rows),
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
    symbol_stats = collect_koch_symbol_stats(matching, symbols=claimed_symbols)
    recent_symbol_stats = collect_koch_symbol_stats(recent, symbols=claimed_symbols)
    listening_probe_rows = collect_koch_listening_probe_exercises(recent)
    confusions = load_confusion_pairs(records, claimed_set_key=claimed_set_key)

    return {
        "version": BURDEN_PROFILE_VERSION,
        "claimed_set_key": claimed_set_key,
        "record_count": len(matching),
        "window_size": max(0, window_size),
        "records_used": len(recent),
        "burdens": {
            "symbol_inventory": koch_symbol_inventory_burden(
                stats,
                lifetime_stats=lifetime_stats,
                symbol_stats=symbol_stats,
                recent_symbol_stats=recent_symbol_stats,
            ),
            "grouping": _koch_grouping_burden(stats, lifetime_stats=lifetime_stats),
            "unit_length": _koch_unit_length_burden(stats, lifetime_stats=lifetime_stats),
            "confusion": _koch_confusion_burden(confusions),
            "signal": koch_listening_conditions_burden(listening_probe_rows),
            "rhythm": _unknown_burden("No Koch cadence-variation contrast probes yet."),
            "anchor": _unknown_burden("No Koch anchor-removal contrast probes yet."),
            "practice_transfer": _unknown_burden(
                "No linked Symbol Recognition to Koch Exercise transfer evidence yet."
            ),
        },
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
    return matching_recognition_records(records, claimed_set_key)


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
    return debt_from_fraction(value)


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
