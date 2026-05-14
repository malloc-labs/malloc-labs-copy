"""Tests for copy_653.sequence.copy_exercises."""

from __future__ import annotations

import pytest

from copy_653 import sequence


KMU = ("K", "M", "U")


def test_uses_only_claimed_symbols():
    result = sequence.generate_copy_exercises(
        claimed_set=KMU,
        exercise_count=20,
        seed=42,
    )
    assert len(result.exercises) == 20
    for exercise in result.exercises:
        assert exercise
        for ch in exercise:
            assert ch in KMU


def test_same_seed_reproduces_exercises():
    a = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=10, seed=42)
    b = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=10, seed=42)
    assert a.exercises == b.exercises
    assert a.seed == b.seed == 42
    assert a.claimed_set == b.claimed_set == KMU


def test_different_seeds_produce_different_exercises():
    a = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=20, seed=1)
    b = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=20, seed=2)
    assert a.exercises != b.exercises


def test_length_bounds_respected():
    result = sequence.generate_copy_exercises(
        claimed_set=KMU,
        exercise_count=50,
        min_length=2,
        max_length=4,
        seed=7,
    )
    for exercise in result.exercises:
        assert 2 <= len(exercise) <= 4


def test_seed_is_concrete_when_omitted():
    result = sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=3)
    assert isinstance(result.seed, int)
    # Replay with the recorded seed reproduces the same exercises.
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


def test_invalid_length_bounds_raise():
    with pytest.raises(ValueError, match="min_length"):
        sequence.generate_copy_exercises(claimed_set=KMU, exercise_count=5, min_length=0)
    with pytest.raises(ValueError, match="max_length"):
        sequence.generate_copy_exercises(
            claimed_set=KMU, exercise_count=5, min_length=3, max_length=2
        )
