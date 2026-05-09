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


def test_koch_order_starts_k_m_u():
    # The published Koch sequence opens K, M, U — the first three
    # symbols whose shapes maximally contrast against each other.
    assert patterns.KOCH_ORDER[:3] == ("K", "M", "U")


def test_koch_first_pair_matches_koch_order_head():
    assert patterns.KOCH_FIRST_PAIR == patterns.KOCH_ORDER[:2]


def test_koch_order_has_no_duplicates():
    assert len(set(patterns.KOCH_ORDER)) == len(patterns.KOCH_ORDER)


def test_every_koch_symbol_has_a_pattern():
    # If KOCH_ORDER ever drifts ahead of PATTERNS the engine would
    # suggest a symbol it can't synthesise.
    for symbol in patterns.KOCH_ORDER:
        assert symbol in patterns.PATTERNS, f"{symbol} in KOCH_ORDER but not in PATTERNS"


def test_next_koch_after_empty_is_first():
    assert patterns.next_koch_after(()) == "K"


def test_next_koch_after_first_pair_is_u():
    assert patterns.next_koch_after(patterns.KOCH_FIRST_PAIR) == "U"


def test_next_koch_after_skips_already_claimed():
    # A learner who already has K, M, U should be suggested R next.
    assert patterns.next_koch_after(("K", "M", "U")) == "R"


def test_next_koch_after_is_case_insensitive():
    assert patterns.next_koch_after(("k", "m")) == "U"


def test_next_koch_after_returns_none_when_all_claimed():
    assert patterns.next_koch_after(patterns.KOCH_ORDER) is None


def test_next_koch_after_ignores_unrelated_claimed_symbols():
    # The learner has free-claimed digits; Koch's letters still flow.
    assert patterns.next_koch_after(("5", "9")) == "K"
