"""Tests for copy_653.sequence.copy_exercises."""

from __future__ import annotations

import pytest

from copy_653 import sequence
from copy_653.sequence.copy_exercises import (
    DEFAULT_CANDIDATE_MULTIPLIER,
    _score_copy_exercise,
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
