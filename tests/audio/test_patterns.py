"""Tests for copy_653.audio.patterns."""

import pytest

from copy_653.audio import patterns


def test_koch_first_pair_is_k_and_m():
    assert patterns.KOCH_FIRST_PAIR == ("K", "M")


def test_pattern_for_k():
    assert patterns.pattern_for("K") == "-.-"


def test_pattern_for_m():
    assert patterns.pattern_for("M") == "--"


def test_pattern_lookup_is_case_insensitive():
    assert patterns.pattern_for("k") == patterns.pattern_for("K")


def test_unknown_symbol_raises_keyerror():
    with pytest.raises(KeyError):
        patterns.pattern_for("?")


def test_all_letters_have_patterns():
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        assert letter in patterns.PATTERNS, f"missing pattern for {letter}"


def test_all_digits_have_patterns():
    for digit in "0123456789":
        assert digit in patterns.PATTERNS, f"missing pattern for {digit}"


def test_patterns_contain_only_dits_and_dahs():
    for symbol, pattern in patterns.PATTERNS.items():
        for char in pattern:
            assert char in {".", "-"}, f"{symbol} pattern has invalid char {char!r}"
