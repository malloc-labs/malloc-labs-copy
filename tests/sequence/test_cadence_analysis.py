from copy_653.sequence.cadence_analysis import (
    apply_cadence_analysis,
    build_cadence_exercise_entries,
    build_cadence_generation_profile,
    latest_gears_for_claimed_set,
    load_band_evidence,
    resolve_gears,
)


def test_build_cadence_generation_profile_records_bands():
    profile = build_cadence_generation_profile(
        claimed_set=("M", "K"),
        candidate_count=20,
        exercise_count=2,
        gears=[0, 1],
    )

    assert profile == {
        "profile_version": "cadence-burden-v1",
        "claimed_set_key": "K M",
        "candidate_count": 20,
        "bands": [{"index": 1, "gear": 0}, {"index": 2, "gear": 1}],
    }


def test_apply_cadence_analysis_selects_latest_complete_attempt():
    entries = build_cadence_exercise_entries(["KM"], scores=[32])
    sent = [
        {
            "symbol": "M",
            "pattern": "--",
            "started_at": 1.0,
            "ended_at": 1.42,
            "leading_gap": "none",
        },
        {
            "symbol": "K",
            "pattern": "-.-",
            "started_at": 2.0,
            "ended_at": 2.54,
            "leading_gap": "word",
        },
        {
            "symbol": "M",
            "pattern": "--",
            "started_at": 2.72,
            "ended_at": 3.14,
            "leading_gap": "character",
        },
    ]
    key_events = [
        {"kind": "dah", "pressed": False, "timestamp": 2.18, "duration_ms": 180.0},
        {"kind": "dit", "pressed": False, "timestamp": 2.36, "duration_ms": 60.0},
        {"kind": "dah", "pressed": False, "timestamp": 2.54, "duration_ms": 180.0},
        {"kind": "dah", "pressed": False, "timestamp": 2.9, "duration_ms": 180.0},
        {"kind": "dah", "pressed": False, "timestamp": 3.14, "duration_ms": 180.0},
    ]

    updated = apply_cadence_analysis(
        entries,
        sent=sent,
        key_events=key_events,
        character_wpm=20,
    )

    exercise = updated[0]
    assert len(exercise["attempts"]) == 2
    assert exercise["attempts"][1]["complete"] is True
    assert exercise["analysis"]["selected_attempt_index"] == 1
    assert exercise["analysis"]["selected_attempt_reason"] == "latest-complete"
    assert exercise["analysis"]["symbol_fraction"] == 1.0
    assert exercise["analysis"]["spacing_fraction"] == 1.0
    assert exercise["analysis"]["formation_fraction"] == 1.0
    assert exercise["analysis"]["gap_timing_fraction"] == 1.0
    assert exercise["attempts"][1]["gaps"][0]["gap_units"] == 3.0


def test_apply_cadence_analysis_penalises_word_gap_mismatch():
    entries = build_cadence_exercise_entries(["K M"], scores=[50])
    sent = [
        {
            "symbol": "K",
            "pattern": "-.-",
            "started_at": 1.0,
            "ended_at": 1.54,
            "leading_gap": "none",
        },
        {
            "symbol": "M",
            "pattern": "--",
            "started_at": 1.72,
            "ended_at": 2.14,
            "leading_gap": "character",
        },
    ]

    updated = apply_cadence_analysis(entries, sent=sent, key_events=[], character_wpm=20)

    analysis = updated[0]["analysis"]
    assert analysis["symbol_fraction"] == 1.0
    assert analysis["spacing_fraction"] == 0.0
    assert analysis["gap_timing_fraction"] == 0.0
    assert analysis["band_state"] == "low"


def test_word_gap_readability_allows_operator_fist_without_exact_gap():
    entries = build_cadence_exercise_entries(["K M"], scores=[50])
    # 900ms after K at 20 WPM is about 15 dit-units: longer than a
    # metronomic 7-unit word gap, but still plainly a readable word gap.
    sent = [
        {
            "symbol": "K",
            "pattern": "-.-",
            "started_at": 1.0,
            "ended_at": 1.54,
            "leading_gap": "none",
        },
        {
            "symbol": "M",
            "pattern": "--",
            "started_at": 2.44,
            "ended_at": 2.86,
            "leading_gap": "word",
        },
    ]

    updated = apply_cadence_analysis(entries, sent=sent, key_events=[], character_wpm=20)

    attempt = updated[0]["attempts"][0]
    assert attempt["gaps"][0]["gap_units"] == 15.0
    assert attempt["gap_timing_fraction"] == 1.0
    assert updated[0]["analysis"]["spacing_fraction"] == 1.0


def test_load_band_evidence_and_resolve_gears_for_cadence():
    def _session(started_at: str, gear: int, fraction: float) -> dict:
        return {
            "mode": "cadence-send",
            "started_at": started_at,
            "claimed_set": ["K", "M"],
            "generation": {
                "claimed_set_key": "K M",
                "bands": [{"index": 1, "gear": gear}],
            },
            "exercises": [
                {
                    "index": 1,
                    "burden_band": 1,
                    "gear": gear,
                    "analysis": {
                        "saved": True,
                        "combined_fraction": fraction,
                        "symbol_fraction": fraction,
                        "spacing_fraction": fraction,
                        "formation_fraction": fraction,
                        "gap_timing_fraction": fraction,
                        "decode_health": 1.0,
                        "band_state": "exact" if fraction >= 1.0 else "low",
                    },
                }
            ],
        }

    records = [
        _session("2026-05-18T10:00:00Z", 0, 1.0),
        _session("2026-05-18T11:00:00Z", 0, 1.0),
        _session("2026-05-18T12:00:00Z", 0, 1.0),
    ]
    evidence = load_band_evidence(records, claimed_set_key="K M")

    assert evidence["bands"][0]["strong_streak"] == 3
    assert evidence["bands"][0]["symbol_fraction"] == 1.0
    assert latest_gears_for_claimed_set(records, claimed_set_key="K M") == {1: 0}
    assert resolve_gears(evidence, current_gears={1: 0}) == {1: 1}
