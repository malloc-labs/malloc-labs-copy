"""Tests for the NATO phonetic anchor wav loader."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from copy_653.letters.wav import load_wav


def _write_wav(
    path: Path,
    samples_int16: list[int],
    sample_rate: int = 48000,
    channels: int = 1,
    sample_width: int = 2,
) -> None:
    """Write a tiny WAV file for fixture purposes."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        if sample_width == 2:
            data = b"".join(struct.pack("<h", s) for s in samples_int16)
        elif sample_width == 1:
            # 8-bit PCM is unsigned in WAV.
            data = bytes((s + 128) & 0xFF for s in samples_int16)
        else:
            raise NotImplementedError(
                f"fixture writer does not support sample_width={sample_width}"
            )
        w.writeframes(data)


def test_loads_real_alpha_recording():
    """The committed alpha.wav loads cleanly and matches the format we expect."""
    repo_root = Path(__file__).resolve().parents[2]
    samples, rate = load_wav(repo_root / "assets/audio/nato_phonetic/alpha.wav")

    assert rate == 48000
    assert samples.dtype == np.float32
    assert samples.ndim == 1
    assert samples.size > 0
    # Normalised range — never exceed full scale.
    assert samples.max() <= 1.0
    assert samples.min() >= -1.0


def test_normalises_int16_to_float32_range(tmp_path):
    """Full-scale negative -> -1.0, zero -> 0.0, near-full positive -> ~1.0."""
    wav = tmp_path / "tiny.wav"
    _write_wav(wav, [-32768, 0, 16384])
    samples, _ = load_wav(wav)

    assert samples.dtype == np.float32
    assert samples.size == 3
    assert samples[0] == pytest.approx(-1.0)
    assert samples[1] == pytest.approx(0.0)
    assert samples[2] == pytest.approx(0.5)


def test_rejects_stereo(tmp_path):
    wav = tmp_path / "stereo.wav"
    _write_wav(wav, [0, 0, 0, 0], channels=2)

    with pytest.raises(ValueError, match="mono"):
        load_wav(wav)


def test_rejects_non_16bit(tmp_path):
    wav = tmp_path / "8bit.wav"
    _write_wav(wav, [0, 64, 127], sample_width=1)

    with pytest.raises(ValueError, match="16-bit"):
        load_wav(wav)


def test_missing_file_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_wav(tmp_path / "does-not-exist.wav")
