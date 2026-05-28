"""Tests for copy_653.voice.lexicon."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copy_653.audio.patterns import KOCH_ORDER, PATTERNS
from copy_653.voice.lexicon import (
    DEFAULT_LEXICON_DIR,
    Lexicon,
    LexiconError,
    load_lexicon,
)

# ---------- bundled-asset checks (the real lexicons must stay valid) ----


def test_bundled_default_lexicon_loads():
    """The shipped *_en.json files must merge into a valid Lexicon."""
    lex = load_lexicon("en")
    assert isinstance(lex, Lexicon)
    assert lex.language == "en"
    assert lex.source_files  # at least one file was discovered


def test_bundled_lexicon_covers_koch_order():
    """Every Koch curriculum symbol has at least one spoken phrase."""
    lex = load_lexicon("en")
    for symbol in KOCH_ORDER:
        assert symbol in lex.entries, f"missing phrases for {symbol!r}"
        assert lex.entries[symbol], f"empty phrase list for {symbol!r}"


def test_bundled_lexicon_symbols_are_subset_of_patterns():
    lex = load_lexicon("en")
    assert set(lex.entries).issubset(PATTERNS.keys())


def test_bundled_lexicon_phrases_are_unique():
    lex = load_lexicon("en")
    flattened = [p for phrases in lex.entries.values() for p in phrases]
    assert len(flattened) == len(set(flattened))


# ---------- helpers -----------------------------------------------------


def _write_lex(path: Path, language: str, entries: dict[str, list[str]]) -> None:
    path.write_text(
        json.dumps(
            {
                "name": path.stem,
                "language": language,
                "category": "test",
                "entries": entries,
            }
        ),
        encoding="utf-8",
    )


def _koch_filler() -> dict[str, list[str]]:
    """One unique placeholder phrase per Koch symbol — used as a covering base."""
    return {sym: [f"placeholder_{i}"] for i, sym in enumerate(KOCH_ORDER)}


# ---------- merge + validation ------------------------------------------


def test_load_lexicon_merges_phrases_for_same_symbol(tmp_path):
    """Two files that both contribute phrases for the same symbol union them."""
    base = _koch_filler()
    _write_lex(tmp_path / "core_xx.json", "xx", base)
    _write_lex(tmp_path / "alias_xx.json", "xx", {"5": ["fife"]})
    lex = load_lexicon("xx", lexicon_dir=tmp_path)
    # 5 keeps its base placeholder *and* gains the alias.
    five_phrases = set(lex.entries["5"])
    assert "fife" in five_phrases
    assert len(five_phrases) == 2


def test_load_lexicon_raises_on_unknown_symbol(tmp_path):
    _write_lex(tmp_path / "broken_xx.json", "xx", {"@": ["at"]})
    with pytest.raises(LexiconError, match="not a known CW pattern"):
        load_lexicon("xx", lexicon_dir=tmp_path)


def test_load_lexicon_raises_on_duplicate_phrase_same_symbol(tmp_path):
    base = _koch_filler()
    a_index = KOCH_ORDER.index("A")
    _write_lex(tmp_path / "a_xx.json", "xx", base)
    # File b redeclares A's exact same placeholder phrase.
    _write_lex(tmp_path / "b_xx.json", "xx", {"A": [f"placeholder_{a_index}"]})
    with pytest.raises(LexiconError, match="duplicate phrase"):
        load_lexicon("xx", lexicon_dir=tmp_path)


def test_load_lexicon_raises_on_duplicate_phrase_different_symbols(tmp_path):
    base = _koch_filler()
    k_index = KOCH_ORDER.index("K")  # K's placeholder is placeholder_0.
    _write_lex(tmp_path / "a_xx.json", "xx", base)
    # File b tries to map B to K's existing placeholder phrase.
    _write_lex(tmp_path / "b_xx.json", "xx", {"B": [f"placeholder_{k_index}"]})
    with pytest.raises(LexiconError, match="duplicate phrase"):
        load_lexicon("xx", lexicon_dir=tmp_path)


def test_load_lexicon_raises_on_koch_coverage_gap(tmp_path):
    # Only covers A, leaves the rest of KOCH_ORDER bare.
    _write_lex(tmp_path / "partial_xx.json", "xx", {"A": ["alpha"]})
    with pytest.raises(LexiconError, match="Koch curriculum symbols"):
        load_lexicon("xx", lexicon_dir=tmp_path)


def test_load_lexicon_raises_on_intra_file_duplicate_phrase(tmp_path):
    entries = _koch_filler()
    # The same phrase listed twice for the same symbol.
    entries["A"] = ["alpha", "alpha"]
    _write_lex(tmp_path / "broken_xx.json", "xx", entries)
    with pytest.raises(LexiconError, match="appears twice"):
        load_lexicon("xx", lexicon_dir=tmp_path)


def test_load_lexicon_raises_on_missing_language(tmp_path):
    with pytest.raises(LexiconError, match="no lexicon files"):
        load_lexicon("zz", lexicon_dir=tmp_path)


def test_load_lexicon_raises_on_language_mismatch(tmp_path):
    # Filename says _en but the JSON declares "xx".
    _write_lex(tmp_path / "wrong_en.json", "xx", {"A": ["alpha"]})
    with pytest.raises(LexiconError, match="language field"):
        load_lexicon("en", lexicon_dir=tmp_path)


def test_load_lexicon_raises_on_malformed_json(tmp_path):
    (tmp_path / "broken_en.json").write_text("{not json}", encoding="utf-8")
    with pytest.raises(LexiconError, match="invalid JSON"):
        load_lexicon("en", lexicon_dir=tmp_path)


def test_load_lexicon_raises_on_uppercase_phrase(tmp_path):
    _write_lex(tmp_path / "case_xx.json", "xx", {"A": ["Alpha"]})
    with pytest.raises(LexiconError, match="must be lower-case"):
        load_lexicon("xx", lexicon_dir=tmp_path)


def test_load_lexicon_raises_on_missing_directory(tmp_path):
    with pytest.raises(LexiconError, match="lexicon directory not found"):
        load_lexicon("en", lexicon_dir=tmp_path / "does-not-exist")


# ---------- accessors ---------------------------------------------------


def test_phrases_returns_sorted_unique():
    lex = load_lexicon("en")
    phrases = lex.phrases()
    assert phrases == tuple(sorted(set(phrases)))


def test_symbol_for_round_trips():
    lex = load_lexicon("en")
    for symbol, phrase_list in lex.entries.items():
        for phrase in phrase_list:
            assert lex.symbol_for(phrase) == symbol


def test_symbol_for_unknown_returns_none():
    lex = load_lexicon("en")
    assert lex.symbol_for("nonsense word that should never be a phrase") is None


def test_default_lexicon_dir_resolves_to_package_assets():
    assert DEFAULT_LEXICON_DIR.is_dir()
    assert DEFAULT_LEXICON_DIR.name == "lexicon"
