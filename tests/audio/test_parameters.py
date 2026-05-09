"""Tests for copy_653.audio.parameters."""

import pytest

from copy_653.audio.parameters import AudioParameters


def test_default_construction_uses_spec_defaults():
    p = AudioParameters()
    assert p.character_speed_wpm == 20
    assert p.effective_speed_wpm == 10
    assert p.tone_frequency_hz == 600
    assert p.sample_rate_hz == 48_000
    assert p.envelope_ramp_seconds == 0.005


def test_is_frozen():
    # Frozen dataclass: assignment to a field should raise.
    p = AudioParameters()
    with pytest.raises(Exception):  # FrozenInstanceError, but we don't import it
        p.character_speed_wpm = 25  # type: ignore[misc]


def test_zero_character_speed_rejected():
    with pytest.raises(ValueError):
        AudioParameters(character_speed_wpm=0)


def test_negative_character_speed_rejected():
    with pytest.raises(ValueError):
        AudioParameters(character_speed_wpm=-5)


def test_effective_speed_above_character_speed_rejected():
    with pytest.raises(ValueError):
        AudioParameters(character_speed_wpm=15, effective_speed_wpm=20)


def test_negative_envelope_ramp_rejected():
    with pytest.raises(ValueError):
        AudioParameters(envelope_ramp_seconds=-0.001)


def test_zero_envelope_ramp_allowed():
    # Zero ramp is valid (synth will skip the envelope work entirely).
    AudioParameters(envelope_ramp_seconds=0.0)
