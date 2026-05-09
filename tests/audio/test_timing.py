"""Tests for copy_653.audio.timing."""

import math

from copy_653.audio import timing
from copy_653.audio.parameters import AudioParameters


def test_dit_seconds_at_20wpm_is_60ms():
    # The standard CW formula: dit = 1.2 / WPM. 20 WPM gives 60 ms.
    assert math.isclose(timing.dit_seconds(20), 0.060)


def test_dah_seconds_is_three_dits():
    assert math.isclose(timing.dah_seconds(20), 3 * timing.dit_seconds(20))


def test_inter_element_seconds_is_one_dit():
    assert math.isclose(timing.inter_element_seconds(20), timing.dit_seconds(20))


def test_inter_character_no_farnsworth_is_three_dits():
    # When effective == character speed, no Farnsworth applies — the
    # gap between characters is the standard 3 dits.
    params = AudioParameters(character_speed_wpm=20, effective_speed_wpm=20)
    assert math.isclose(timing.inter_character_seconds(params), 3 * 0.060)


def test_inter_word_no_farnsworth_is_seven_dits():
    params = AudioParameters(character_speed_wpm=20, effective_speed_wpm=20)
    assert math.isclose(timing.inter_word_seconds(params), 7 * 0.060)


def test_farnsworth_extends_inter_character_spacing():
    # At 20/10 WPM Farnsworth, inter-character spacing is longer than
    # the no-Farnsworth case (3 dits = 180 ms at 20 WPM).
    params = AudioParameters(character_speed_wpm=20, effective_speed_wpm=10)
    assert timing.inter_character_seconds(params) > 0.180


def test_farnsworth_total_word_duration_matches_effective_wpm():
    # The whole point of Farnsworth: total time per PARIS-equivalent
    # word equals 60 / effective_wpm seconds.
    params = AudioParameters(character_speed_wpm=20, effective_speed_wpm=10)
    intra_seconds = 31 * timing.dit_seconds(20)
    space_seconds = 4 * timing.inter_character_seconds(params) + timing.inter_word_seconds(params)
    total = intra_seconds + space_seconds
    expected = 60.0 / 10
    assert math.isclose(total, expected, rel_tol=1e-9)
