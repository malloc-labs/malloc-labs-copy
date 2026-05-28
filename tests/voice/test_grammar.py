"""Tests for copy_653.voice.grammar."""

from __future__ import annotations

from copy_653.voice.grammar import UNKNOWN_TOKEN, build_grammar, resolve_symbols
from copy_653.voice.lexicon import load_lexicon

# ---------- build_grammar ---------------------------------------------------


def test_build_grammar_returns_every_phrase_plus_unk():
    lex = load_lexicon("en")
    grammar = build_grammar(lex)
    for phrase in lex.phrases():
        assert phrase in grammar
    assert UNKNOWN_TOKEN in grammar


def test_build_grammar_is_unique_and_stable():
    lex = load_lexicon("en")
    grammar = build_grammar(lex)
    assert len(grammar) == len(set(grammar))
    # Call twice — output must be identical (sorted, deterministic).
    assert build_grammar(lex) == grammar


def test_build_grammar_only_appends_unk_once_if_present():
    lex = load_lexicon("en")
    grammar = build_grammar(lex)
    assert grammar.count(UNKNOWN_TOKEN) == 1


# ---------- resolve_symbols -------------------------------------------------


def test_resolve_symbols_single_phrase_returns_one_symbol():
    lex = load_lexicon("en")
    assert resolve_symbols(lex, "alpha") == ["A"]
    assert resolve_symbols(lex, "kilo") == ["K"]


def test_resolve_symbols_multiword_phrase_matched_as_one():
    lex = load_lexicon("en")
    # "x ray" → X, not "x" then "ray".
    assert resolve_symbols(lex, "x ray") == ["X"]
    assert resolve_symbols(lex, "question mark") == ["?"]


def test_resolve_symbols_batch_utterance():
    """The screenshot regression: a long utterance fully tokenises."""
    lex = load_lexicon("en")
    assert resolve_symbols(lex, "uniform kilo mike uniform mike") == ["U", "K", "M", "U", "M"]


def test_resolve_symbols_mixed_singles_and_multiword():
    lex = load_lexicon("en")
    assert resolve_symbols(lex, "alpha question mark bravo") == ["A", "?", "B"]
    assert resolve_symbols(lex, "x ray alpha") == ["X", "A"]
    assert resolve_symbols(lex, "alpha x ray bravo") == ["A", "X", "B"]


def test_resolve_symbols_skips_unknown_words_silently():
    lex = load_lexicon("en")
    # "er" is not in the lexicon; the surrounding NATO words still resolve.
    assert resolve_symbols(lex, "alpha er bravo") == ["A", "B"]
    # Leading and trailing junk dropped too.
    assert resolve_symbols(lex, "um alpha um") == ["A"]


def test_resolve_symbols_handles_repeats():
    lex = load_lexicon("en")
    assert resolve_symbols(lex, "alpha alpha alpha") == ["A", "A", "A"]


def test_resolve_symbols_normalises_case_and_whitespace():
    lex = load_lexicon("en")
    assert resolve_symbols(lex, "ALPHA") == ["A"]
    assert resolve_symbols(lex, "  Alpha   Bravo  ") == ["A", "B"]


def test_resolve_symbols_handles_empty_and_unk():
    lex = load_lexicon("en")
    assert resolve_symbols(lex, "") == []
    assert resolve_symbols(lex, "   ") == []
    assert resolve_symbols(lex, UNKNOWN_TOKEN) == []


def test_resolve_symbols_returns_empty_for_no_matches():
    lex = load_lexicon("en")
    assert resolve_symbols(lex, "nothing here matches") == []


def test_resolve_symbols_aliases_resolve_to_same_symbol():
    lex = load_lexicon("en")
    # niner and nine both map to 9.
    assert resolve_symbols(lex, "nine niner") == ["9", "9"]
    # period and stop both map to "."
    assert resolve_symbols(lex, "period stop") == [".", "."]


def test_resolve_symbols_returns_new_list_each_call():
    lex = load_lexicon("en")
    a = resolve_symbols(lex, "alpha")
    b = resolve_symbols(lex, "alpha")
    assert a == b
    assert a is not b
