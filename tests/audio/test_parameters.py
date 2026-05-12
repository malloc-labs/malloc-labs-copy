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
    assert p.amplitude == 0.3
    assert p.receiver_bed == 0
    assert p.cadence_variation == 0


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


def test_zero_amplitude_rejected():
    # Silence-by-default is not what anyone asks for; reject explicitly
    # so the failure is immediate and obvious.
    with pytest.raises(ValueError):
        AudioParameters(amplitude=0.0)


def test_negative_amplitude_rejected():
    with pytest.raises(ValueError):
        AudioParameters(amplitude=-0.1)


def test_amplitude_above_one_rejected():
    # Above 1 would clip in the float32 buffer.
    with pytest.raises(ValueError):
        AudioParameters(amplitude=1.5)


def test_amplitude_at_one_allowed():
    # The boundary is closed at 1.0 — full-scale is permitted, just
    # not the default.
    AudioParameters(amplitude=1.0)


def test_default_output_device_is_none():
    # None means "use sounddevice's system default output".
    p = AudioParameters()
    assert p.output_device is None


def test_output_device_accepts_int_index():
    p = AudioParameters(output_device=3)
    assert p.output_device == 3


def test_output_device_accepts_string_name():
    # Passed through to sounddevice as a substring match against
    # device names; not validated at construction time.
    p = AudioParameters(output_device="Mac mini Speakers")
    assert p.output_device == "Mac mini Speakers"


def test_receiver_bed_range_is_bounded():
    AudioParameters(receiver_bed=10)
    with pytest.raises(ValueError, match="receiver_bed"):
        AudioParameters(receiver_bed=11)
    with pytest.raises(ValueError, match="receiver_bed"):
        AudioParameters(receiver_bed=-1)


def test_cadence_variation_range_is_bounded():
    AudioParameters(cadence_variation=5)
    with pytest.raises(ValueError, match="cadence_variation"):
        AudioParameters(cadence_variation=6)
    with pytest.raises(ValueError, match="cadence_variation"):
        AudioParameters(cadence_variation=-1)
