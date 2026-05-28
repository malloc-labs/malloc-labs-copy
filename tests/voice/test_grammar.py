"""Tests for copy_653.voice.grammar."""

from __future__ import annotations

from copy_653.voice.grammar import UNKNOWN_TOKEN, build_grammar, resolve_symbol
from copy_653.voice.lexicon import load_lexicon


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


def test_resolve_symbol_round_trips_via_grammar():
    lex = load_lexicon("en")
    for phrase in lex.phrases():
        assert resolve_symbol(lex, phrase) is not None


def test_resolve_symbol_handles_unk():
    lex = load_lexicon("en")
    assert resolve_symbol(lex, UNKNOWN_TOKEN) is None


def test_resolve_symbol_handles_empty_and_whitespace():
    lex = load_lexicon("en")
    assert resolve_symbol(lex, "") is None
    assert resolve_symbol(lex, "   ") is None


def test_resolve_symbol_is_case_insensitive():
    lex = load_lexicon("en")
    # "alpha" is in the bundled NATO lexicon.
    assert resolve_symbol(lex, "ALPHA") == "A"
    assert resolve_symbol(lex, "  Alpha  ") == "A"
