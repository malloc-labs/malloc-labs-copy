"""Tests for focus-letter word-detection generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from copy_653.audio.parameters import AudioParameters
from copy_653.sequence import (
    FOUNDATION_LEXICON_SCHEMA_VERSION,
    LexiconEntry,
    generate_word_detection,
    load_foundation_lexicon,
)


def _entry(
    word: str,
    *,
    rhythm_diversity: float = 1.0,
    transitions: int = 1,
    dit_count: int = 1,
    dah_count: int = 1,
    frequency: int = 100,
) -> LexiconEntry:
    return LexiconEntry(
        word=word,
        letters=tuple(word),
        morse=" ".join(word),
        length=len(word),
        frequency=frequency,
        frequency_rank=frequency,
        commonness="test",
        rhythm_signature="test",
        rhythm_diversity=rhythm_diversity,
        transitions=transitions,
        repeat_pressure="low",
        dit_count=dit_count,
        dah_count=dah_count,
    )


def test_load_foundation_lexicon_bundled_asset():
    schema_version, entries = load_foundation_lexicon()

    assert schema_version == FOUNDATION_LEXICON_SCHEMA_VERSION
    assert len(entries) > 4_000
    assert all(3 <= entry.length <= 5 for entry in entries)
    assert any("k" in entry.letters for entry in entries)


def test_generate_word_detection_uses_focus_not_known_subset():
    params = AudioParameters(character_speed_wpm=25, effective_speed_wpm=25)
    lexicon = (
        _entry("oak", rhythm_diversity=2.0, transitions=3, dit_count=4, dah_count=2),
        _entry("mum", rhythm_diversity=1.0, transitions=1),
    )

    generated = generate_word_detection(
        focus_set=("K",),
        duration_seconds=10.0,
        params=params,
        lexicon=lexicon,
        seed=0,
    )

    assert [entry.word for entry in generated.words] == ["oak"]
    assert [symbol.symbol for symbol in generated.symbols] == ["O", "A", "K"]
    assert generated.focus_set == ("K",)
    assert set(generated.words[0].letters) != {"k"}


def test_generate_word_detection_is_replayable_with_seed():
    params = AudioParameters(character_speed_wpm=25, effective_speed_wpm=25)
    lexicon = (
        _entry("mum", rhythm_diversity=3.0, transitions=2),
        _entry("mere", rhythm_diversity=2.0, transitions=3),
        _entry("emu", rhythm_diversity=1.0, transitions=1),
    )

    first = generate_word_detection(
        focus_set=("M",),
        duration_seconds=20.0,
        params=params,
        lexicon=lexicon,
        seed=1234,
    )
    second = generate_word_detection(
        focus_set=("M",),
        duration_seconds=20.0,
        params=params,
        lexicon=lexicon,
        seed=1234,
    )

    assert [entry.word for entry in first.words] == [entry.word for entry in second.words]
    assert first.symbols == second.symbols
    assert first.seed == second.seed == 1234
    assert first.ranking == "rhythmic-diverse"


def test_generate_word_detection_returns_empty_when_duration_too_short():
    params = AudioParameters(character_speed_wpm=5, effective_speed_wpm=5)
    generated = generate_word_detection(
        focus_set=("K",),
        duration_seconds=0.01,
        params=params,
        lexicon=(_entry("oak"),),
        seed=99,
    )

    assert generated.words == ()
    assert generated.symbols == ()
    assert generated.seed == 99


def test_generate_word_detection_rejects_focus_without_candidates():
    params = AudioParameters(character_speed_wpm=25, effective_speed_wpm=25)

    with pytest.raises(ValueError, match="no foundation lexicon words contain focus symbols"):
        generate_word_detection(
            focus_set=("Z",),
            duration_seconds=10.0,
            params=params,
            lexicon=(_entry("mum"),),
            seed=1,
        )


def test_load_foundation_lexicon_rejects_wrong_schema(tmp_path: Path):
    lexicon_path = tmp_path / "lexicon.json"
    lexicon_path.write_text('{"schema_version": 999, "words": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        load_foundation_lexicon(lexicon_path)
