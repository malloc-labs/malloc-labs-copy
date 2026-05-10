"""WAV file loader for the NATO phonetic anchor recordings.

The recordings live in ``assets/audio/nato_phonetic/{alpha..zulu}.wav``
as 16-bit mono PCM. This module reads them off disk and converts the
raw frames to the float32 sample buffers ``sounddevice`` expects.

Per spec §1.5 the loader fails honestly. Anything that is not 16-bit
mono PCM raises a clear :class:`ValueError`; we do not silently
downmix or re-quantise. If the recordings ever change shape, the next
``play-letter`` will say so plainly rather than producing garbled or
silent output.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    """Load a 16-bit mono PCM WAV file as (float32 samples, sample rate).

    Samples are normalised to the ``[-1.0, 1.0]`` range expected by
    sounddevice. The returned array is 1-D mono float32; the integer
    sample rate is returned alongside so the caller can play back at
    the recording's native rate.

    Raises :class:`FileNotFoundError` if the file does not exist.
    Raises :class:`ValueError` if the file is not 16-bit mono PCM —
    we do not silently mix or quantise to fit (spec §1.5).
    """
    if not path.is_file():
        raise FileNotFoundError(f"WAV file not found: {path}")

    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        sample_width = w.getsampwidth()
        sample_rate = w.getframerate()
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)

    if channels != 1:
        raise ValueError(
            f"{path.name}: expected mono, got {channels} channels. "
            "v0 only supports 1-channel recordings."
        )
    if sample_width != 2:
        raise ValueError(
            f"{path.name}: expected 16-bit PCM (sample_width=2), "
            f"got sample_width={sample_width}. v0 only supports 16-bit."
        )

    # Signed 16-bit PCM → float32 in [-1, 1]. 32768 (not 32767) is the
    # standard divisor: full negative scale is -32768, so dividing by
    # 32768 keeps the buffer symmetric and never produces > 1.0.
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / np.float32(32768.0)
    return samples, sample_rate
