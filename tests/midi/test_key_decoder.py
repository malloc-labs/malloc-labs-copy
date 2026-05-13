"""Tests for already-formed key element decoding."""

import pytest

from copy_653.midi import DecodedSymbol, KeyDecoder, KeyElement


def test_decodes_k_after_character_gap():
    decoder = KeyDecoder(dit_seconds=0.1)

    assert decoder.push(KeyElement("dah", 0.0)) is None
    assert decoder.push(KeyElement("dit", 0.4)) is None
    assert decoder.push(KeyElement("dah", 0.6)) is None

    assert decoder.tick(1.2) == DecodedSymbol(
        pattern="-.-",
        symbol="K",
        started_at=0.0,
        ended_at=0.9,
    )


def test_next_element_after_character_gap_flushes_previous_symbol():
    decoder = KeyDecoder(dit_seconds=0.1)

    assert decoder.push(KeyElement("dit", 0.0)) is None
    decoded = decoder.push(KeyElement("dah", 0.5))

    assert decoded == DecodedSymbol(
        pattern=".",
        symbol="E",
        started_at=0.0,
        ended_at=0.1,
    )

    assert decoder.tick(1.1) == DecodedSymbol(
        pattern="-",
        symbol="T",
        started_at=0.5,
        ended_at=0.8,
    )


def test_unknown_pattern_returns_no_symbol():
    decoder = KeyDecoder(dit_seconds=0.1)

    for index in range(6):
        assert decoder.push(KeyElement("dit", index * 0.2)) is None

    assert decoder.tick(1.5) == DecodedSymbol(
        pattern="......",
        symbol=None,
        started_at=0.0,
        ended_at=1.1,
    )


def test_tick_does_not_finalize_before_character_gap():
    decoder = KeyDecoder(dit_seconds=0.1)

    decoder.push(KeyElement("dit", 0.0))

    assert decoder.tick(0.39) is None
    assert decoder.tick(0.4) == DecodedSymbol(
        pattern=".",
        symbol="E",
        started_at=0.0,
        ended_at=0.1,
    )
    assert decoder.tick(1.0) is None


def test_rejects_non_monotonic_elements():
    decoder = KeyDecoder(dit_seconds=0.1)

    decoder.push(KeyElement("dah", 1.0))

    with pytest.raises(ValueError, match="monotonic"):
        decoder.push(KeyElement("dit", 1.2))


def test_rejects_invalid_timing_configuration():
    with pytest.raises(ValueError, match="dit_seconds"):
        KeyDecoder(dit_seconds=0)

    with pytest.raises(ValueError, match="character_gap_dits"):
        KeyDecoder(dit_seconds=0.1, character_gap_dits=0)
