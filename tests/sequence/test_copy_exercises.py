"""Tests for copy_653.sequence.copy_exercises."""

from __future__ import annotations

import pytest

from copy_653 import sequence
from copy_653.sequence.copy_exercises import (
    DEFAULT_CANDIDATE_MULTIPLIER,
    _score_copy_exercise,
    _has_identical_run,
    _slot_range,
)

KMU = ("K", "M", "U")


def _words(exercise: str) -> list[str]:
    return exercise.split(" ")


def test_uses_only_claimed_symbols():
    result = sequence.generate_copy_exercises(
        claimed_set=KMU,
        exercise_count=5,
        seed=42,
    )
    assert len(result.exercises) == 5
    for exercise in result.exercises:
        for word in _words(exercise):
            assert word
            for ch in word:
                assert ch in KMU


def test_sentence_structure_respects_word_bounds():
    result = sequence.generate_copy_exercises(
        claimed_set=KMU,
        exercise_count=20,
        min_words=3,
        max_words=6,
        min_word_length=2,
        max_word_length=4,
        seed=7,
    )
    for exercise in result.exercises:
        words = _words(exercise)
        assert 3 <= len(words) <= 6
        for word in words:
            assert 2 <= len(word) <= 4


def test_same_seed_reproduces_exercises():
    a = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=5, seed=42)
    b = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=5, seed=42)
    assert a.exercises == b.exercises
    assert a.seed == b.seed == 42
    assert a.claimed_set == b.claimed_set == KMU


def test_different_seeds_produce_different_exercises():
    a = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=10, seed=1)
    b = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=10, seed=2)
    assert a.exercises != b.exercises


def test_seed_is_concrete_when_omitted():
    result = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=3)
    assert isinstance(result.seed, int)
    replay = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=3, seed=result.seed)
    assert replay.exercises == result.exercises


def test_empty_claimed_set_raises():
    with pytest.raises(ValueError, match="non-empty"):
        sequence.generate_copy_exercises(claimed_set=(), exercise_count=5)


def test_duplicate_claimed_set_raises():
    with pytest.raises(ValueError, match="duplicates"):
        sequence.generate_copy_exercises(claimed_set=("K", "K"), exercise_count=5)


def test_unknown_symbol_raises():
    with pytest.raises(ValueError, match="unknown symbol"):
        sequence.generate_copy_exercises(claimed_set=("K", "!"), exercise_count=5)


def test_non_positive_exercise_count_raises():
    with pytest.raises(ValueError, match="exercise_count"):
        sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=0)


def test_invalid_word_count_bounds_raise():
    with pytest.raises(ValueError, match="min_words"):
        sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=5, min_words=0)
    with pytest.raises(ValueError, match="max_words"):
        sequence.generate_copy_exercises(
            claimed_set=KMU, exercise_count=5, min_words=4, max_words=3
        )


def test_invalid_word_length_bounds_raise():
    with pytest.raises(ValueError, match="min_word_length"):
        sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=5, min_word_length=0)
    with pytest.raises(ValueError, match="max_word_length"):
        sequence.generate_copy_exercises(
            claimed_set=KMU,
            exercise_count=5,
            min_word_length=3,
            max_word_length=2,
        )


# ---------- scoring + band selection (the two-layer generator) ----------


def test_score_monotone_on_canonical_progression():
    # Lifted from docs/notes/cadence-difficulty.md §1: the intended
    # easy→hard ramp for the K/M/U stage.
    canonical = ["M", "KU", "KMU", "K MU", "UU KMU UM"]
    scores = [_score_copy_exercise(ex) for ex in canonical]
    assert scores == sorted(scores), f"non-monotone canonical ramp: {scores}"


def test_score_penalises_word_gaps_over_extra_symbol():
    # Two groups should cost more than one group of the same total
    # length, even though the symbol count is identical.
    assert _score_copy_exercise("K MU") > _score_copy_exercise("KMU")


def test_score_penalises_symbol_switches():
    assert _score_copy_exercise("KU") > _score_copy_exercise("KK")


def test_result_carries_scores_and_candidate_count():
    result = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=5, seed=42)
    assert len(result.scores) == len(result.exercises) == 5
    assert result.candidate_count == DEFAULT_CANDIDATE_MULTIPLIER * 5
    # Scores are computed by the exposed scorer for each returned exercise.
    assert all(
        score == _score_copy_exercise(exercise)
        for score, exercise in zip(result.scores, result.exercises)
    )


def test_exercises_returned_in_non_decreasing_score_order():
    result = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=5, seed=42)
    assert list(result.scores) == sorted(result.scores)


def test_custom_candidate_count_honored():
    result = sequence.generate_copy_exercises(
        claimed_set=KMU, exercise_count=5, candidate_count=50, seed=42
    )
    assert result.candidate_count == 50
    assert len(result.exercises) == 5


def test_candidate_count_below_exercise_count_raises():
    with pytest.raises(ValueError, match="candidate_count"):
        sequence.generate_copy_exercises(
            claimed_set=KMU, exercise_count=5, candidate_count=4, seed=42
        )


def test_band_coverage_one_pick_per_quintile():
    # Replay the same seed with the public API and reconstruct the
    # candidate pool to assert each returned exercise came from a
    # distinct quintile band of the sorted pool.
    from random import Random

    seed = 314159
    exercise_count = 5
    candidate_count = 20
    min_words, max_words = 1, 2
    min_len, max_len = 1, 3
    rng = Random(seed)
    pool: list[str] = []
    for _ in range(candidate_count):
        word_count = rng.randint(min_words, max_words)
        words = []
        for _ in range(word_count):
            length = rng.randint(min_len, max_len)
            words.append("".join(rng.choice(KMU) for _ in range(length)))
        pool.append(" ".join(words))
    sorted_pool = sorted(pool, key=lambda ex: (_score_copy_exercise(ex), pool.index(ex)))

    result = sequence.generate_copy_exercises(
        claimed_set=KMU,
        exercise_count=exercise_count,
        candidate_count=candidate_count,
        min_words=min_words,
        max_words=max_words,
        min_word_length=min_len,
        max_word_length=max_len,
        seed=seed,
    )

    bands_hit: set[int] = set()
    for exercise in result.exercises:
        # Find which band of the sorted pool this exercise sits in.
        for band_index in range(exercise_count):
            lo = band_index * candidate_count // exercise_count
            hi = (band_index + 1) * candidate_count // exercise_count
            if exercise in sorted_pool[lo:hi]:
                bands_hit.add(band_index)
                break
    assert bands_hit == set(range(exercise_count))


def test_default_exercises_have_at_most_two_groups():
    # The default cap is two symbol groups so three-group exercises
    # like ``KKM UU UKM`` never appear at the hard end of the ramp.
    result = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=5, seed=42)
    for exercise in result.exercises:
        assert len(exercise.split(" ")) <= 2, exercise


def test_max_identical_run_rejects_triples_across_word_breaks():
    assert _has_identical_run("KKK", max_run=2)
    assert _has_identical_run("KK KM", max_run=2)
    assert not _has_identical_run("KK M", max_run=2)


def test_max_identical_run_filter_limits_generated_repetition():
    result = sequence.generate_copy_exercises(
        claimed_set=("K", "M"),
        exercise_count=20,
        candidate_count=80,
        seed=20260518,
        max_identical_run=2,
    )

    assert len(result.exercises) == 20
    for exercise in result.exercises:
        assert not _has_identical_run(exercise, max_run=2), exercise


def test_max_identical_run_raises_when_pool_cannot_be_drawn():
    with pytest.raises(ValueError, match="max_identical_run"):
        sequence.generate_copy_exercises(
            claimed_set=("K",),
            exercise_count=1,
            candidate_count=1,
            min_words=1,
            max_words=1,
            min_word_length=3,
            max_word_length=3,
            seed=1,
            max_identical_run=2,
        )


def test_slot_range_gear_zero_covers_full_band():
    # Default behaviour: each slot draws from its own quintile band.
    assert _slot_range(0, 5, 20, 0) == (0, 4)
    assert _slot_range(2, 5, 20, 0) == (8, 12)
    assert _slot_range(4, 5, 20, 0) == (16, 20)


def test_slot_range_gear_one_uses_upper_half_of_same_band():
    assert _slot_range(0, 5, 20, 1) == (2, 4)
    assert _slot_range(2, 5, 20, 1) == (10, 12)


def test_slot_range_gear_two_shifts_to_next_band():
    # Slot 0 at gear 2 should pull from band 1's full range; slot 2 should
    # pull from band 3.
    assert _slot_range(0, 5, 20, 2) == (4, 8)
    assert _slot_range(2, 5, 20, 2) == (12, 16)


def test_slot_range_gear_two_clamps_at_top_band_to_gear_one():
    # No band above slot 4, so gear 2 falls back to gear 1 behaviour.
    assert _slot_range(4, 5, 20, 2) == _slot_range(4, 5, 20, 1) == (18, 20)


def test_generator_gears_shift_scores_upward():
    # Gear 2 across the board should produce a score profile no lower
    # than the gear-0 baseline at every slot — each slot is drawing
    # from at least its own band.
    baseline = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=5, seed=2026)
    shifted = sequence.generate_copy_exercises(
        claimed_set=KMU, exercise_count=5, seed=2026, gears=[2, 2, 2, 2, 1]
    )
    # The last slot at gear 1 is the upper half of band 4; slots 0-3 at
    # gear 2 pull from bands 1-4 respectively. Pairwise the shifted
    # scores should be >= the baseline at every slot (gear 0 may pull
    # the easy end of its band; the shifted ramp cannot pull below it).
    for base_score, shifted_score in zip(baseline.scores, shifted.scores):
        assert shifted_score >= base_score


def test_generator_gears_ignored_when_none():
    # gears=None should behave exactly like the previous default.
    a = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=5, seed=7, gears=None)
    b = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=5, seed=7)
    assert a.exercises == b.exercises


def test_generator_gears_clamped_to_supported_range():
    # Gear 99 is treated as gear 2; gear -3 as gear 0.
    high = sequence.generate_copy_exercises(
        claimed_set=KMU, exercise_count=5, seed=11, gears=[99, 99, 99, 99, 99]
    )
    two = sequence.generate_copy_exercises(
        claimed_set=KMU, exercise_count=5, seed=11, gears=[2, 2, 2, 2, 2]
    )
    assert high.exercises == two.exercises


def test_degenerate_single_symbol_set_does_not_crash():
    # claimed_set=("K",) produces a pool where every candidate scores
    # in a narrow range; bands may have ties at the boundary, but the
    # generator should still return ``exercise_count`` items in
    # non-decreasing score order.
    result = sequence.generate_copy_exercises(claimed_set=("K",), exercise_count=5, seed=42)
    assert len(result.exercises) == 5
    assert list(result.scores) == sorted(result.scores)
    for exercise in result.exercises:
        for ch in exercise.replace(" ", ""):
            assert ch == "K"
