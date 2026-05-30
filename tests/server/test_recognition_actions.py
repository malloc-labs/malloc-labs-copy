import random

from copy_653.server.recognition_actions import (
    _generate_recognition_exercise,
    _recognition_kind_for_gear,
    _say_after_for_slot,
)


def test_recognition_gear_zero_generates_four_single_symbols():
    exercise = _generate_recognition_exercise(("K", "M"), gear=0, rng=random.Random(1))

    assert len(exercise) == 4
    assert all(len(word) == 1 for word in exercise)
    assert _recognition_kind_for_gear(0) == "single-symbols"


def test_recognition_gear_two_generates_symbol_pairs():
    exercise = _generate_recognition_exercise(("K", "M", "U"), gear=2, rng=random.Random(2))

    assert len(exercise) == 2
    assert all(len(word) == 2 for word in exercise)
    assert _recognition_kind_for_gear(2) == "pairs"


def test_recognition_gear_three_generates_words_up_to_three_symbols():
    exercise = _generate_recognition_exercise(("K", "M", "U"), gear=3, rng=random.Random(3))

    assert len(exercise) == 2
    assert all(1 <= len(word) <= 3 for word in exercise)
    assert any(len(word) > 1 for word in exercise)
    assert _recognition_kind_for_gear(3) == "words"


def test_recognition_say_after_scaffold_by_gear_and_slot():
    assert _say_after_for_slot(gear=0, exercise_index=5) is True
    assert _say_after_for_slot(gear=1, exercise_index=1) is True
    assert _say_after_for_slot(gear=1, exercise_index=2) is True
    assert _say_after_for_slot(gear=1, exercise_index=3) is False
    assert _say_after_for_slot(gear=2, exercise_index=1) is False
    assert _say_after_for_slot(gear=3, exercise_index=1) is False
