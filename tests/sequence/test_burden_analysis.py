from copy_653.sequence.burden_analysis import (
    DEBT_HIGH,
    DEBT_LOW,
    DEBT_MODERATE,
    DEBT_UNKNOWN,
    DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE,
    load_koch_attention_response,
    load_koch_burden_profile,
    load_recognition_burden_profile,
)
from copy_653.sequence.recognition_analysis import (
    OUTCOME_CAUGHT_CORRECT,
    OUTCOME_CAUGHT_SUBSTITUTION,
    OUTCOME_CORRECT,
    OUTCOME_MISS,
    OUTCOME_SUBSTITUTION,
)


def _slot(truth: str, outcome: str = OUTCOME_CORRECT) -> dict:
    committed = truth if outcome == OUTCOME_CORRECT else None
    if outcome == OUTCOME_SUBSTITUTION:
        committed = "R" if truth != "R" else "K"
    return {
        "truth": truth,
        "outcome": outcome,
        "committed": committed,
        "tokens": [committed] if committed else [],
    }


def _exercise(
    *,
    index: int = 1,
    gear: int,
    fraction: float,
    slots: list[dict],
    committed=(),
    caught=(),
) -> dict:
    return {
        "index": index,
        "gear": gear,
        "analysis": {
            "saved": True,
            "has_evidence": True,
            "combined_fraction": fraction,
            "counts": {
                OUTCOME_CORRECT: sum(1 for slot in slots if slot.get("outcome") == OUTCOME_CORRECT),
                OUTCOME_SUBSTITUTION: sum(
                    1 for slot in slots if slot.get("outcome") == OUTCOME_SUBSTITUTION
                ),
                OUTCOME_CAUGHT_CORRECT: sum(
                    1 for slot in slots if slot.get("outcome") == OUTCOME_CAUGHT_CORRECT
                ),
                OUTCOME_CAUGHT_SUBSTITUTION: sum(
                    1 for slot in slots if slot.get("outcome") == OUTCOME_CAUGHT_SUBSTITUTION
                ),
                OUTCOME_MISS: sum(1 for slot in slots if slot.get("outcome") == OUTCOME_MISS),
            },
            "slots": slots,
            "committed_confusions": [list(pair) for pair in committed],
        },
        "timing_analysis": {
            "caught_confusions": [list(pair) for pair in caught],
        },
    }


def _record(started_at: str, *exercises: dict, claimed_set_key: str = "K M R U") -> dict:
    return {
        "mode": "recognition",
        "started_at": started_at,
        "claimed_set": claimed_set_key.split(),
        "generation": {
            "claimed_set_key": claimed_set_key,
            "gear": exercises[0]["gear"] if exercises else 0,
        },
        "exercises": list(exercises),
    }


def _timed_record(
    minute: int,
    *exercises: dict,
    claimed_set_key: str = "K M R U",
    duration_seconds: int = 48,
) -> dict:
    started = f"2026-06-01T12:{minute:02d}:00Z"
    ended = f"2026-06-01T12:{minute:02d}:{duration_seconds:02d}Z"
    record = _record(started, *exercises, claimed_set_key=claimed_set_key)
    record["ended_at"] = ended
    return record


def _tag_listening_probe(record: dict, conditions: list[str]) -> dict:
    record["generation"]["listening_probe"] = {
        "version": "recognition-listening-conditions-v1",
        "conditions": ["default", "textured"],
    }
    for exercise, condition in zip(record["exercises"], conditions, strict=False):
        exercise["listening_probe"] = "recognition-listening-conditions-v1"
        exercise["listening_condition"] = condition
        exercise["s"] = 7 if condition == "default" else 5
        exercise["t"] = 3 if condition == "default" else 5
    return record


def _tag_rhythm_probe(record: dict, probe_indexes: set[int], *, baseline: int = 1) -> dict:
    record["audio"] = {"cadence_variation": baseline}
    record["generation"]["rhythm_probe"] = {
        "version": "recognition-rhythm-v1",
        "baseline_cadence_variation": baseline,
        "probe_cadence_variation": baseline + 1,
        "exercise_index": 3,
    }
    for exercise in record["exercises"]:
        if exercise["index"] in probe_indexes:
            exercise["rhythm_probe"] = "recognition-rhythm-v1"
            exercise["baseline_cadence_variation"] = baseline
            exercise["cadence_variation"] = baseline + 1
    return record


def test_burden_profile_reports_low_symbol_debt_with_unknown_probe_axes():
    records = [
        _record(
            "2026-06-01T12:00:00Z",
            _exercise(
                gear=0,
                fraction=1.0,
                slots=[_slot("K"), _slot("M"), _slot("R"), _slot("U")],
            ),
        )
        for _ in range(20)
    ]

    profile = load_recognition_burden_profile(
        records,
        claimed_set_key="K M R U",
        window_size=20,
    )

    assert profile["version"] == "burden-profile-v1"
    symbol = profile["burdens"]["symbol_inventory"]
    assert symbol["debt"] == DEBT_LOW
    assert symbol["confidence"] == "high"
    assert {row["symbol"]: row["fraction"] for row in symbol["symbols"]} == {
        "K": 1.0,
        "M": 1.0,
        "R": 1.0,
        "U": 1.0,
    }
    assert {row["symbol"]: row["signal"] for row in symbol["symbols"]} == {
        "K": "stable",
        "M": "stable",
        "R": "stable",
        "U": "stable",
    }
    assert profile["burdens"]["signal"]["debt"] == DEBT_UNKNOWN
    rhythm = profile["burdens"]["rhythm"]
    assert rhythm["debt"] == DEBT_UNKNOWN
    assert rhythm["response"] == "baseline_observed"
    assert "Higher rhythm variation has not been probed yet." in rhythm["evidence"][0]
    anchor = profile["burdens"]["anchor"]
    assert anchor["debt"] == DEBT_UNKNOWN
    assert anchor["confidence"] == "high"
    assert anchor["response"] == "not_currently_used"
    assert "context streams" in anchor["evidence"][1]


def test_burden_profile_ignores_untagged_st_history_for_listening_conditions():
    exercise = _exercise(
        gear=0,
        fraction=1.0,
        slots=[_slot("K"), _slot("M")],
    )
    exercise["s"] = 5
    exercise["t"] = 5
    record = _record("2026-06-01T12:00:00Z", exercise)

    profile = load_recognition_burden_profile([record], claimed_set_key="K M R U")

    listening = profile["burdens"]["signal"]
    assert listening["debt"] == DEBT_UNKNOWN
    assert "No controlled default-vs-textured recognition probe yet." in listening["evidence"]


def test_burden_profile_reports_listening_conditions_from_tagged_probe():
    record = _tag_listening_probe(
        _record(
            "2026-06-01T12:00:00Z",
            _exercise(gear=0, fraction=0.80, slots=[_slot("K"), _slot("M")]),
            _exercise(gear=0, fraction=0.90, slots=[_slot("K"), _slot("M")]),
            _exercise(gear=0, fraction=0.80, slots=[_slot("R"), _slot("U")]),
            _exercise(gear=0, fraction=0.90, slots=[_slot("R"), _slot("U")]),
        ),
        ["default", "textured", "default", "textured"],
    )

    profile = load_recognition_burden_profile([record], claimed_set_key="K M R U")

    listening = profile["burdens"]["signal"]
    assert listening["debt"] == DEBT_MODERATE
    assert listening["confidence"] == "medium"
    assert listening["response"] == "texture_helped"
    assert listening["delta"] == 0.1
    assert (
        "More textured signal performed better than the default signal" in listening["evidence"][0]
    )


def test_burden_profile_reports_rhythm_from_tagged_probe():
    record = _tag_rhythm_probe(
        _record(
            "2026-06-01T12:00:00Z",
            _exercise(gear=0, fraction=1.0, slots=[_slot("K"), _slot("M")]),
            _exercise(index=2, gear=0, fraction=1.0, slots=[_slot("R"), _slot("U")]),
            _exercise(
                index=3,
                gear=0,
                fraction=0.5,
                slots=[_slot("K"), _slot("M", OUTCOME_MISS)],
            ),
            _exercise(
                index=4,
                gear=0,
                fraction=0.5,
                slots=[_slot("R"), _slot("U", OUTCOME_MISS)],
            ),
        ),
        {3, 4},
    )

    profile = load_recognition_burden_profile([record], claimed_set_key="K M R U")

    rhythm = profile["burdens"]["rhythm"]
    assert rhythm["debt"] == DEBT_HIGH
    assert rhythm["confidence"] == "medium"
    assert rhythm["response"] == "rhythm_hurt"
    assert rhythm["delta"] == -0.5
    assert "Raised rhythm variation performed worse than baseline" in rhythm["evidence"][0]


def test_burden_profile_detects_unit_length_debt_separate_from_singles():
    singles = [
        _record(
            f"2026-06-01T12:{minute:02d}:00Z",
            _exercise(
                gear=0,
                fraction=1.0,
                slots=[_slot("K"), _slot("M"), _slot("R"), _slot("U")],
            ),
        )
        for minute in range(10)
    ]
    pairs = [
        _record(
            f"2026-06-01T13:{minute:02d}:00Z",
            _exercise(
                gear=1,
                fraction=0.8,
                slots=[_slot("K"), _slot("R", OUTCOME_SUBSTITUTION)],
                committed=[("R", "K")],
            ),
        )
        for minute in range(10)
    ]

    profile = load_recognition_burden_profile(
        [*singles, *pairs],
        claimed_set_key="K M R U",
        window_size=20,
    )

    unit = profile["burdens"]["unit_length"]
    assert unit["debt"] == DEBT_MODERATE
    assert unit["confidence"] == "high"
    assert unit["exercise_count"] == 10
    assert unit["average_fraction"] == 0.8
    assert "Single-symbol recognition averaged 100.0%" in unit["evidence"][1]


def test_burden_profile_reports_high_symbol_and_confusion_debt():
    records = [
        _record(
            f"2026-06-01T12:{minute:02d}:00Z",
            _exercise(
                gear=0,
                fraction=0.5,
                slots=[
                    _slot("K"),
                    _slot("M"),
                    _slot("R", OUTCOME_MISS),
                    _slot("U", OUTCOME_SUBSTITUTION),
                ],
                committed=[("U", "R")],
            ),
        )
        for minute in range(6)
    ]

    profile = load_recognition_burden_profile(
        records,
        claimed_set_key="K M R U",
        window_size=6,
    )

    symbol = profile["burdens"]["symbol_inventory"]
    assert symbol["debt"] == DEBT_HIGH
    assert any("Weakest lifetime symbol R at 0.0%" in item for item in symbol["evidence"])

    confusion = profile["burdens"]["confusion"]
    assert confusion["debt"] == DEBT_HIGH
    assert confusion["committed"][0] == {"target": "U", "typed": "R", "count": 6}
    assert confusion["caught"] == []


def test_burden_profile_uses_review_softening_for_confusion_debt():
    record = _record(
        "2026-06-01T12:00:00Z",
        {
            "index": 1,
            "gear": 0,
            "analysis": {
                "has_evidence": True,
                "combined_fraction": 0.0,
                "counts": {
                    OUTCOME_CORRECT: 0,
                    OUTCOME_SUBSTITUTION: 2,
                    OUTCOME_CAUGHT_CORRECT: 0,
                    OUTCOME_CAUGHT_SUBSTITUTION: 0,
                    OUTCOME_MISS: 0,
                },
                "slots": [
                    _slot("R", OUTCOME_SUBSTITUTION),
                    _slot("R", OUTCOME_SUBSTITUTION),
                ],
                "committed_confusions": [["R", "K"], ["R", "K"]],
                "caught_confusions": [],
            },
            "timing_analysis": {
                "has_evidence": True,
                "caught_confusions": [["R", "K"], ["R", "K"]],
            },
        },
    )

    profile = load_recognition_burden_profile(
        [record],
        claimed_set_key="K M R U",
        window_size=1,
    )

    confusion = profile["burdens"]["confusion"]
    assert confusion["debt"] == DEBT_LOW
    assert confusion["committed"] == []
    assert confusion["caught"] == [{"target": "R", "typed": "K", "count": 2}]


def test_symbol_burden_uses_since_introduction_evidence_not_only_recent_window():
    early = [
        _record(
            f"2026-06-01T10:{minute:02d}:00Z",
            _exercise(
                gear=0,
                fraction=1.0,
                slots=[_slot("M")],
            ),
            claimed_set_key="K M",
        )
        for minute in range(20)
    ]
    recent = [
        _record(
            "2026-06-01T12:00:00Z",
            _exercise(
                gear=0,
                fraction=0.8,
                slots=[_slot("M", OUTCOME_SUBSTITUTION)],
            ),
            claimed_set_key="K M R U",
        ),
        _record(
            "2026-06-01T12:01:00Z",
            _exercise(
                gear=0,
                fraction=1.0,
                slots=[_slot("M"), _slot("R"), _slot("U")],
            ),
            claimed_set_key="K M R U",
        ),
    ]

    profile = load_recognition_burden_profile(
        [*early, *recent],
        claimed_set_key="K M R U",
        window_size=2,
    )

    symbol = profile["burdens"]["symbol_inventory"]
    m_row = next(row for row in symbol["symbols"] if row["symbol"] == "M")
    assert symbol["debt"] == DEBT_LOW
    assert symbol["confidence"] == "low"
    assert m_row["lifetime_exposures"] == 22
    assert m_row["lifetime_correct"] == 21
    assert m_row["recent_exposures"] == 2
    assert m_row["recent_correct"] == 1
    assert m_row["signal"] == "watch"
    assert any(
        "Weakest recent symbol M at 50.0% over 2 exposures" in item for item in symbol["evidence"]
    )


def test_burden_profile_filters_claimed_set_key():
    records = [
        _record(
            "2026-06-01T12:00:00Z",
            _exercise(gear=0, fraction=1.0, slots=[_slot("K")]),
            claimed_set_key="K M",
        ),
        _record(
            "2026-06-01T12:01:00Z",
            _exercise(gear=0, fraction=0.0, slots=[_slot("R", OUTCOME_MISS)]),
            claimed_set_key="K M R U",
        ),
    ]

    profile = load_recognition_burden_profile(records, claimed_set_key="K M")

    assert profile["records_used"] == 1
    assert profile["burdens"]["symbol_inventory"]["debt"] == DEBT_LOW


def test_burden_profile_default_window_is_longer_than_progression_window():
    records = [
        _record(
            f"2026-06-01T12:{minute:02d}:00Z",
            _exercise(gear=0, fraction=1.0, slots=[_slot("K")]),
            claimed_set_key="K M",
        )
        for minute in range(DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE + 2)
    ]

    profile = load_recognition_burden_profile(records, claimed_set_key="K M")

    assert profile["window_size"] == DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE
    assert profile["records_used"] == DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE


def test_recognition_burden_profile_estimates_time_to_targets():
    records = []
    for minute in range(10):
        slots = [
            _slot("K", OUTCOME_SUBSTITUTION),
            _slot("M"),
            _slot("R"),
            _slot("U"),
        ]
        records.append(
            _timed_record(
                minute,
                _exercise(gear=0, fraction=0.75, slots=slots),
                duration_seconds=48,
            )
        )
    for minute in range(10, 30):
        slots = [
            _slot("K", OUTCOME_SUBSTITUTION if minute < 13 else OUTCOME_CORRECT),
            _slot("M"),
            _slot("R", OUTCOME_SUBSTITUTION if minute < 12 else OUTCOME_CORRECT),
            _slot("U"),
        ]
        records.append(
            _timed_record(
                minute,
                _exercise(gear=0, fraction=0.875, slots=slots),
                duration_seconds=48,
            )
        )

    profile = load_recognition_burden_profile(
        records,
        claimed_set_key="K M R U",
        window_size=20,
    )

    estimate = profile["estimated_time"]
    assert estimate["version"] == "recognition-estimated-time-v1"
    assert estimate["next_symbol"] == "E"
    assert estimate["current"]["sessions"] == 30
    assert estimate["current"]["practice_seconds"] == 1440
    assert estimate["current"]["correct"] == 105
    assert estimate["current"]["total"] == 120
    assert estimate["pace"]["seconds_per_session"] == 48
    assert estimate["pace"]["slots_per_session"] == 4

    estimates = {row["key"]: row for row in estimate["estimates"]}
    assert estimates["aggregate_90_recent"]["status"] == "estimated"
    assert estimates["aggregate_90_recent"]["sessions"] == 20
    assert estimates["aggregate_90_recent"]["total_seconds"] == 2400
    assert estimates["claimed_symbols_90_best"]["blocking_symbol"] == "K"
    assert estimates["claimed_symbols_90_best"]["sessions"] == 100
    assert estimates["claimed_symbols_90_settled_range"]["sessions_low"] == 125
    assert estimates["claimed_symbols_90_settled_range"]["sessions_high"] == 167


def _koch_exercise(
    *,
    band: int,
    gear: int,
    played: str,
    answer: str,
    fraction: float,
    symbol_correct: int,
    symbol_available: int,
    spacing_correct: int,
    spacing_available: int,
    s: int | None = None,
    t: int | None = None,
) -> dict:
    exercise = {
        "index": band,
        "played": played,
        "answer": answer,
        "burden_band": band,
        "gear": gear,
        "analysis": {
            "saved": True,
            "combined_fraction": fraction,
            "symbol_correct_units": symbol_correct,
            "symbol_available_units": symbol_available,
            "spacing_correct_units": spacing_correct,
            "spacing_available_units": spacing_available,
        },
    }
    if s is not None:
        exercise["s"] = s
    if t is not None:
        exercise["t"] = t
    return exercise


def _koch_record(
    started_at: str,
    *exercises: dict,
    claimed_set_key: str = "K M R U",
) -> dict:
    return {
        "mode": "koch-exercise",
        "started_at": started_at,
        "claimed_set": claimed_set_key.split(),
        "generation": {
            "claimed_set_key": claimed_set_key,
            "bands": [
                {"index": exercise["burden_band"], "gear": exercise["gear"]}
                for exercise in exercises
            ],
        },
        "exercises": list(exercises),
    }


def test_koch_burden_profile_separates_symbols_grouping_and_band_provenance():
    profile = load_koch_burden_profile(
        [
            _koch_record(
                "2026-06-03T18:42:00Z",
                _koch_exercise(
                    band=4,
                    gear=1,
                    played="DE URU U UM",
                    answer="DE URU UUM",
                    fraction=0.875,
                    symbol_correct=6,
                    symbol_available=6,
                    spacing_correct=1,
                    spacing_available=2,
                ),
            )
        ],
        claimed_set_key="K M R U",
        window_size=5,
    )

    burdens = profile["burdens"]
    assert burdens["symbol_inventory"]["debt"] == DEBT_LOW
    assert burdens["symbol_inventory"]["fraction"] == 1.0
    assert burdens["grouping"]["debt"] == DEBT_HIGH
    assert burdens["grouping"]["fraction"] == 0.5
    assert burdens["unit_length"]["debt"] == DEBT_MODERATE
    assert burdens["unit_length"]["bands"] == [
        {"band": 4, "average_fraction": 0.875, "exercise_count": 1, "current_gear": 1}
    ]
    assert "band 4" in burdens["unit_length"]["evidence"][0]
    assert "gear 1" in burdens["unit_length"]["evidence"][0]


def test_koch_burden_profile_reports_confusion_debt_from_substitutions():
    records = [
        _koch_record(
            f"2026-06-03T18:{minute:02d}:00Z",
            _koch_exercise(
                band=3,
                gear=2,
                played="DE MKR",
                answer="DE MKU",
                fraction=0.8,
                symbol_correct=2,
                symbol_available=3,
                spacing_correct=0,
                spacing_available=0,
            ),
        )
        for minute in range(4)
    ]

    profile = load_koch_burden_profile(records, claimed_set_key="K M R U")

    confusion = profile["burdens"]["confusion"]
    assert confusion["debt"] == DEBT_HIGH
    assert confusion["committed"][0] == {"target": "R", "typed": "U", "count": 4}
    assert profile["burdens"]["signal"]["debt"] == DEBT_UNKNOWN


def test_koch_attention_response_compares_lower_and_higher_s_conditions():
    records = []
    for minute in range(4):
        records.append(
            _koch_record(
                f"2026-06-03T18:{minute:02d}:00Z",
                _koch_exercise(
                    band=1,
                    gear=3,
                    played="DE MKR",
                    answer="DE MKR",
                    fraction=1.0,
                    symbol_correct=3,
                    symbol_available=3,
                    spacing_correct=0,
                    spacing_available=0,
                    s=5,
                    t=7,
                ),
                _koch_exercise(
                    band=2,
                    gear=3,
                    played="DE M KR",
                    answer="DE MKR",
                    fraction=0.75,
                    symbol_correct=3,
                    symbol_available=3,
                    spacing_correct=0,
                    spacing_available=1,
                    s=8,
                    t=9,
                ),
                _koch_exercise(
                    band=3,
                    gear=3,
                    played="DE MKR",
                    answer="DE MKR",
                    fraction=1.0,
                    symbol_correct=3,
                    symbol_available=3,
                    spacing_correct=0,
                    spacing_available=0,
                    s=5,
                    t=7,
                ),
                _koch_exercise(
                    band=3,
                    gear=3,
                    played="DE RKM",
                    answer="DE RKM",
                    fraction=0.75,
                    symbol_correct=3,
                    symbol_available=3,
                    spacing_correct=0,
                    spacing_available=0,
                    s=8,
                    t=9,
                ),
            )
        )

    profile = load_koch_attention_response(records, claimed_set_key="K M R U")

    lower, higher = profile["conditions"]
    assert profile["version"] == "attention-response-v1"
    assert profile["exercise_count"] == 16
    assert lower["label"] == "Lower S / more texture"
    assert lower["st_range"] == "S5 / T7"
    assert lower["axes"]["symbols"]["response"] == "neutral"
    assert lower["axes"]["grouping"]["response"] == "unknown"
    assert lower["axes"]["unit_length"]["response"] == "helped"
    assert lower["axes"]["overall"]["response"] == "helped"
    assert lower["metrics"]["perfect_exercises"] == 8
    assert higher["label"] == "Higher S / cleaner signal"
    assert higher["st_range"] == "S8 / T9"
    assert higher["axes"]["overall"]["response"] == "hurt"


def test_koch_attention_response_requires_per_exercise_st_evidence():
    profile = load_koch_attention_response(
        [
            _koch_record(
                "2026-06-03T18:00:00Z",
                _koch_exercise(
                    band=1,
                    gear=3,
                    played="DE MKR",
                    answer="DE MKR",
                    fraction=1.0,
                    symbol_correct=3,
                    symbol_available=3,
                    spacing_correct=0,
                    spacing_available=0,
                ),
            )
        ],
        claimed_set_key="K M R U",
    )

    assert profile["exercise_count"] == 0
    assert profile["conditions"][0]["st_range"] == "not observed"
    assert profile["conditions"][0]["axes"]["overall"]["response"] == "unknown"
