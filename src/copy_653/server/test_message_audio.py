"""Signal-texture test message synthesis."""

from __future__ import annotations

from typing import Final

import numpy as np

from copy_653.audio import synth, texture, timing
from copy_653.audio.parameters import AudioParameters

MARCONI_TEST_MESSAGE: Final = (
    ("ARE", "YOU", "READY"),
    ("CAN", "YOU", "HEAR", "ME"),
    ("YES", "LOUD", "AND", "CLEAR"),
)
INTER_PHRASE_SECONDS: Final = 2.0


def build_marconi_test_message(params: AudioParameters) -> np.ndarray:
    """Render the fixed settings-page test message using ``params``."""
    parts: list[np.ndarray] = []
    gap_index = 0
    context = "marconi-test-message"
    inter_char_seconds = timing.inter_character_seconds(params)
    inter_word_seconds = timing.inter_word_seconds(params)

    for phrase_index, phrase in enumerate(MARCONI_TEST_MESSAGE):
        if phrase_index > 0:
            parts.append(synth.synthesize_silence(INTER_PHRASE_SECONDS, params))

        for word_index, word in enumerate(phrase):
            if word_index > 0:
                parts.append(
                    synth.synthesize_silence(
                        texture.cadence_gap_seconds(
                            inter_word_seconds,
                            params,
                            gap_index=gap_index,
                            context=context,
                        ),
                        params,
                    )
                )
                gap_index += 1

            for symbol_index, symbol in enumerate(word):
                if symbol_index > 0:
                    parts.append(
                        synth.synthesize_silence(
                            texture.cadence_gap_seconds(
                                inter_char_seconds,
                                params,
                                gap_index=gap_index,
                                context=context,
                            ),
                            params,
                        )
                    )
                    gap_index += 1
                parts.append(synth.synthesize_symbol(symbol, params))

    samples = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    return texture.add_receiver_bed(samples, params, context=context)
