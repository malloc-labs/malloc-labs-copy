from copy_653.sequence.burden_analysis import (
    DEBT_HIGH,
    DEBT_LOW,
    DEBT_MODERATE,
    DEBT_UNKNOWN,
    load_recognition_burden_profile,
)
from copy_653.sequence.recognition_analysis import (
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
    gear: int,
    fraction: float,
    slots: list[dict],
    committed=(),
    caught=(),
) -> dict:
    return {
        "index": 1,
        "gear": gear,
        "analysis": {
            "has_evidence": True,
            "combined_fraction": fraction,
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
    assert profile["burdens"]["signal"]["debt"] == DEBT_UNKNOWN
    assert profile["burdens"]["rhythm"]["debt"] == DEBT_UNKNOWN
    assert profile["burdens"]["anchor"]["debt"] == DEBT_UNKNOWN


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
                caught=[("U", "R")],
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
    assert any("Weakest symbol R at 0.0%" in item for item in symbol["evidence"])

    confusion = profile["burdens"]["confusion"]
    assert confusion["debt"] == DEBT_HIGH
    assert confusion["committed"][0] == {"target": "U", "typed": "R", "count": 6}
    assert confusion["caught"][0] == {"target": "U", "typed": "R", "count": 6}


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
