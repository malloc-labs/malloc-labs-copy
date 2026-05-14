"""Tests for copy_653.sequence.copy_exercises."""

from __future__ import annotations

import pytest

from copy_653 import sequence


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
    replay = sequence.generate_copy_exercises(
        claimed_set=KMU, exercise_count=3, seed=result.seed
    )
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
        sequence.generate_copy_exercises(
            claimed_set=KMU, exercise_count=5, min_word_length=0
        )
    with pytest.raises(ValueError, match="max_word_length"):
        sequence.generate_copy_exercises(
            claimed_set=KMU,
            exercise_count=5,
            min_word_length=3,
            max_word_length=2,
        )
