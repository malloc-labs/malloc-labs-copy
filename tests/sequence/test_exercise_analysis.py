from copy_653.sequence.exercise_analysis import (
    analyse_answer,
    apply_answers_to_entries,
    build_exercise_entries,
    build_generation_profile,
    spacing_weight_for_claimed_set,
    strip_fixed_anchor,
)


def test_strip_fixed_anchor_removes_only_leading_de():
    assert strip_fixed_anchor("DE KMK") == "KMK"
    assert strip_fixed_anchor("  de   km mk  ") == "KM MK"
    assert strip_fixed_anchor("K DE M") == "K DE M"


def test_build_generation_profile_records_bands_and_candidate_count():
    profile = build_generation_profile(
        claimed_set=("M", "K"),
        candidate_count=20,
        exercise_count=2,
        gears=[0, 1],
    )

    assert profile == {
        "profile_version": "koch-burden-v1",
        "claimed_set_key": "K M",
        "candidate_count": 20,
        "bands": [{"index": 1, "gear": 0}, {"index": 2, "gear": 1}],
    }


def test_build_exercise_entries_persists_burden_metadata():
    entries = build_exercise_entries(["DE K", "DE KMK"], scores=[20, 52])

    assert entries[0]["played"] == "DE K"
    assert entries[0]["core"] == "K"
    assert entries[0]["burden_score"] == 20
    assert entries[0]["burden_band"] == 1
    assert entries[0]["analysis"]["saved"] is False
    assert entries[1]["core"] == "KMK"
    assert entries[1]["burden_band"] == 2


def test_analyse_answer_counts_partial_and_blank_saved_answers():
    partial = analyse_answer(
        played="DE KMK",
        answer="DE KK",
        exercise_index=2,
        burden_score=52,
        burden_band=2,
        gear=0,
        claimed_set_size=2,
    )
    blank = analyse_answer(
        played="DE KMK",
        answer="",
        exercise_index=2,
        burden_score=52,
        burden_band=2,
        gear=0,
        claimed_set_size=2,
    )

    assert partial["saved"] is True
    assert partial["symbol_correct_units"] == 2
    assert partial["symbol_available_units"] == 3
    # 2/3 symbols correct, no word boundaries to evaluate — the combined
    # fraction is just the symbol fraction (0.667), which lands in "low".
    assert partial["band_state"] == "low"
    assert blank["symbol_correct_units"] == 0
    assert blank["symbol_available_units"] == 3
    assert blank["band_state"] == "low"


def test_analyse_answer_tracks_spacing_separately_from_symbols():
    analysis = analyse_answer(
        played="DE KM K",
        answer="DE KMK",
        exercise_index=1,
        burden_score=58,
        burden_band=1,
        gear=0,
        claimed_set_size=2,
    )

    assert analysis["symbol_correct_units"] == 3
    assert analysis["symbol_available_units"] == 3
    assert analysis["spacing_correct_units"] == 0
    assert analysis["spacing_available_units"] == 1
    # At claimed_set_size=2, spacing weight is 0.5; missing every boundary
    # halves the combined fraction even with perfect symbols.
    assert analysis["spacing_weight"] == 0.5
    assert analysis["band_state"] == "low"


def test_spacing_weight_for_claimed_set_decays_with_size():
    assert spacing_weight_for_claimed_set(1) == 0.5
    assert spacing_weight_for_claimed_set(2) == 0.5
    assert spacing_weight_for_claimed_set(4) == 0.25
    assert spacing_weight_for_claimed_set(10) == 0.15
    assert spacing_weight_for_claimed_set(40) == 0.15


def test_analyse_answer_spacing_weight_shrinks_at_larger_claimed_sets():
    analysis = analyse_answer(
        played="DE KM K",
        answer="DE KMK",
        exercise_index=1,
        burden_score=58,
        burden_band=1,
        gear=0,
        claimed_set_size=10,
    )
    # Same input as the small-set case but with size=10: spacing weight
    # drops to 0.15 so a single-boundary miss leaves the combined fraction
    # at 0.85, which is "steady".
    assert analysis["spacing_weight"] == 0.15
    assert analysis["band_state"] == "steady"


def test_apply_answers_to_entries_merges_answer_analysis():
    entries = build_exercise_entries(["DE KM", "DE K M"], scores=[32, 42])
    updated = apply_answers_to_entries(entries, ["DE KM", "DE K"], claimed_set_size=2)

    assert updated[0]["answer"] == "DE KM"
    assert updated[0]["analysis"]["band_state"] == "exact"
    assert updated[1]["answer"] == "DE K"
    assert updated[1]["analysis"]["symbol_correct_units"] == 1


def test_apply_answers_to_entries_dampens_repeated_exercise_evidence():
    entries = build_exercise_entries(["DE KM", "DE KM", "DE KM"], scores=[32, 32, 32])
    updated = apply_answers_to_entries(entries, ["DE KM", "DE KM", "DE KM"], claimed_set_size=2)

    assert updated[0]["analysis"]["repeat_weight"] == 1.0
    assert updated[1]["analysis"]["repeat_weight"] == 0.7
    assert updated[2]["analysis"]["repeat_weight"] == 0.5
    assert updated[0]["analysis"]["evidence"] > updated[1]["analysis"]["evidence"]
    assert updated[1]["analysis"]["evidence"] > updated[2]["analysis"]["evidence"]
