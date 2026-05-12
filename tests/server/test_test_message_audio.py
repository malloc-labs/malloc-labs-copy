"""Tests for the Settings-page signal texture test message."""

from __future__ import annotations

from copy_653.audio.parameters import AudioParameters
from copy_653.server.test_message_audio import build_marconi_test_message


def test_marconi_test_message_renders_audio_with_phrase_gaps():
    params = AudioParameters(
        character_speed_wpm=20,
        effective_speed_wpm=20,
        sample_rate_hz=8_000,
        receiver_bed=0,
        cadence_variation=0,
    )

    samples = build_marconi_test_message(params)

    assert samples.dtype.name == "float32"
    assert samples.size > params.sample_rate_hz * 4
