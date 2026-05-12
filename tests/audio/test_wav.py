"""Tests for generated WAV encoding."""

from __future__ import annotations

import io
import wave

import numpy as np

from copy_653.audio.wav import encode_pcm16_wav


def test_encode_pcm16_wav_writes_mono_file():
    samples = np.array([-1.0, 0.0, 0.5, 1.0], dtype=np.float32)
    data = encode_pcm16_wav(samples, 8_000)

    with wave.open(io.BytesIO(data), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 8_000
        assert wav.getnframes() == 4


def test_encode_pcm16_wav_rejects_invalid_sample_rate():
    try:
        encode_pcm16_wav(np.zeros(1, dtype=np.float32), 0)
    except ValueError as exc:
        assert "sample_rate_hz" in str(exc)
    else:
        raise AssertionError("expected invalid sample rate to raise")
