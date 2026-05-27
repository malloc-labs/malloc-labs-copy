"""Signal-texture preview audio synthesis.

Builds a short chunk of random CW from the learner's claimed symbol set,
suitable for looping playback while the learner tweaks S / T / cadence
controls on the settings page.
"""

from __future__ import annotations

import random

import numpy as np

from copy_653.audio import synth, texture, timing
from copy_653.audio.parameters import AudioParameters

# Target roughly 4-6 seconds per chunk so the loop feels natural
# without making the learner wait long for a texture change to take
# effect on the next iteration.
_MIN_WORDS = 2
_MAX_WORDS = 4
_MIN_WORD_LEN = 2
_MAX_WORD_LEN = 4


def build_texture_preview(
    params: AudioParameters,
    claimed: tuple[str, ...],
    *,
    seed: int | None = None,
) -> np.ndarray:
    """Render a short random CW passage from ``claimed`` with full texture."""
    if not claimed:
        return np.zeros(0, dtype=np.float32)

    rng = random.Random(seed)
    symbols = list(claimed)

    words: list[str] = []
    n_words = rng.randint(_MIN_WORDS, _MAX_WORDS)
    for _ in range(n_words):
        length = rng.randint(_MIN_WORD_LEN, _MAX_WORD_LEN)
        words.append("".join(rng.choice(symbols) for _ in range(length)))

    context = f"texture-preview:{seed or 0}"
    samples = synth.synthesize_words(words, params)

    tail = synth.synthesize_silence(
        timing.inter_word_seconds(params) * 2,
        params,
    )
    samples = np.concatenate([samples, tail])

    return texture.add_receiver_bed(samples, params, context=context)
