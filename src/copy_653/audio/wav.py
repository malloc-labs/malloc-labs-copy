"""WAV encoding helpers for generated audio buffers."""

from __future__ import annotations

import io
import wave

import numpy as np


def encode_pcm16_wav(samples: np.ndarray, sample_rate_hz: int) -> bytes:
    """Encode mono float samples to little-endian 16-bit PCM WAV bytes."""
    if sample_rate_hz <= 0:
        raise ValueError(f"sample_rate_hz must be positive, got {sample_rate_hz}")

    clipped = np.clip(samples.astype(np.float32, copy=False), -1.0, 1.0)
    pcm = (clipped * np.float32(32767.0)).astype("<i2")

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate_hz)
        w.writeframes(pcm.tobytes())
    return out.getvalue()
