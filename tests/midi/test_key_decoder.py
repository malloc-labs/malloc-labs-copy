"""Tests for already-formed key element decoding."""

import pytest

from copy_653.midi import DecodedSymbol, KeyDecoder, KeyElement


def test_decodes_k_after_character_gap():
    decoder = KeyDecoder(dit_seconds=0.1)

    assert decoder.push(KeyElement("dah", 0.0, 0.3)) is None
    assert decoder.push(KeyElement("dit", 0.4, 0.5)) is None
    assert decoder.push(KeyElement("dah", 0.6, 0.9)) is None

    assert decoder.tick(1.2) == DecodedSymbol(
        pattern="-.-",
        symbol="K",
        started_at=0.0,
        ended_at=0.9,
    )


def test_next_element_after_character_gap_flushes_previous_symbol():
    decoder = KeyDecoder(dit_seconds=0.1)

    assert decoder.push(KeyElement("dit", 0.0, 0.1)) is None
    decoded = decoder.push(KeyElement("dah", 0.5, 0.8))

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
        leading_gap="character",
    )


def test_unknown_pattern_returns_no_symbol():
    decoder = KeyDecoder(dit_seconds=0.1)

    for index in range(6):
        start = index * 0.2
        assert decoder.push(KeyElement("dit", start, start + 0.1)) is None

    assert decoder.tick(1.5) == DecodedSymbol(
        pattern="......",
        symbol=None,
        started_at=0.0,
        ended_at=1.1,
    )


def test_tick_does_not_finalize_before_character_gap():
    decoder = KeyDecoder(dit_seconds=0.1)

    decoder.push(KeyElement("dit", 0.0, 0.1))

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

    decoder.push(KeyElement("dah", 1.0, 1.3))

    with pytest.raises(ValueError, match="monotonic"):
        decoder.push(KeyElement("dit", 1.2, 1.3))


def test_records_word_gap_across_tick_finalised_symbols():
    """Regression: a pause spanning a tick-induced flush must still classify
    the next symbol's leading gap, not silently collapse to ``"none"``."""
    decoder = KeyDecoder(
        dit_seconds=0.1,
        character_gap_seconds=0.3,
        word_gap_seconds=0.7,
    )

    # Send "E" — single dit at t=0.
    assert decoder.push(KeyElement("dit", 0.0, 0.1)) is None
    # Tick during silence finalises the E (>= character_gap_seconds).
    assert decoder.tick(0.5) == DecodedSymbol(
        pattern=".",
        symbol="E",
        started_at=0.0,
        ended_at=0.1,
    )

    # Long pause — 5 s passes before next paddle. The pre-fix decoder lost
    # _last_element_end on the tick flush, so this dah came back as
    # leading_gap="none". Now the gap is computed against the prior E's end.
    assert decoder.push(KeyElement("dah", 5.0, 5.3)) is None
    assert decoder.tick(5.7) == DecodedSymbol(
        pattern="-",
        symbol="T",
        started_at=5.0,
        ended_at=5.3,
        leading_gap="word",
    )


def test_records_word_gap_before_symbol():
    decoder = KeyDecoder(
        dit_seconds=0.1,
        character_gap_seconds=0.3,
        word_gap_seconds=0.7,
    )

    assert decoder.push(KeyElement("dah", 0.0, 0.3)) is None
    assert decoder.push(KeyElement("dit", 0.4, 0.5)) is None
    assert decoder.push(KeyElement("dah", 0.6, 0.9)) is None
    assert decoder.push(KeyElement("dah", 1.7, 2.0)) == DecodedSymbol(
        pattern="-.-",
        symbol="K",
        started_at=0.0,
        ended_at=0.9,
    )
    assert decoder.push(KeyElement("dah", 2.1, 2.4)) is None

    assert decoder.tick(2.7) == DecodedSymbol(
        pattern="--",
        symbol="M",
        started_at=1.7,
        ended_at=2.4,
        leading_gap="word",
    )


def test_flush_pending_returns_none_with_no_marks():
    decoder = KeyDecoder(dit_seconds=0.1)

    assert decoder.flush_pending() is None


def test_flush_pending_unconditionally_finalises_current_marks():
    """Timer-driven flushes call flush_pending; they already waited the
    character gap externally and must not be second-guessed by a cross-clock
    comparison (e.g. browser perf.now → time.monotonic calibration bias)."""
    decoder = KeyDecoder(dit_seconds=0.1)

    assert decoder.push(KeyElement("dit", 0.0, 0.1)) is None
    # No tick() time check — flush regardless of elapsed time. This guards
    # against the case where the element's timestamp is in a slightly
    # different clock domain than the caller's "now".
    assert decoder.flush_pending() == DecodedSymbol(
        pattern=".",
        symbol="E",
        started_at=0.0,
        ended_at=0.1,
    )
    # Subsequent push detects the gap to the next element correctly.
    assert decoder.push(KeyElement("dah", 5.0, 5.3)) is None
    assert decoder.flush_pending() == DecodedSymbol(
        pattern="-",
        symbol="T",
        started_at=5.0,
        ended_at=5.3,
        leading_gap="word",
    )


def test_rejects_element_end_before_start():
    decoder = KeyDecoder(dit_seconds=0.1)

    with pytest.raises(ValueError, match="end timestamp"):
        decoder.push(KeyElement("dit", 1.0, 0.9))


def test_rejects_invalid_timing_configuration():
    with pytest.raises(ValueError, match="dit_seconds"):
        KeyDecoder(dit_seconds=0)

    with pytest.raises(ValueError, match="character_gap_dits"):
        KeyDecoder(dit_seconds=0.1, character_gap_dits=0)

    with pytest.raises(ValueError, match="character_gap_seconds"):
        KeyDecoder(dit_seconds=0.1, character_gap_seconds=0)

    with pytest.raises(ValueError, match="word_gap_seconds"):
        KeyDecoder(dit_seconds=0.1, word_gap_seconds=0)
