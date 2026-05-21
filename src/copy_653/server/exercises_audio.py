"""Koch Exercises audio assembly for the server.

Builds a single audio buffer and a session-relative timeline from a list
of short exercises produced by
:func:`copy_653.sequence.generate_copy_exercises`. Each exercise is a
space-separated string of pseudo-words (e.g. ``"K MK KM"``); words are
rendered with intra-character spacing inside and inter-word spacing
between, both Farnsworth-aware. Between exercises, silence equal to 2×
the inter-word gap is inserted so the exercise boundary is perceptibly
distinct from a within-exercise word boundary while still scaling with
the configured Farnsworth settings.

The receiver bed is applied once over the full assembled buffer rather
than per exercise so the floor continues uninterrupted across
inter-exercise silence. Otherwise the bed would dip to true zero
between exercises and that level shift becomes an audible "exercise
ended" marker for learners on headphones or decent speakers — exactly
the cue the bed exists to mask.

This module is pure: no I/O, no clock, no module-level random state.
The WebSocket server decides when to start a session and how to emit
events; this module decides what audio buffer and symbol schedule the
learner hears.
"""

from __future__ import annotations

import numpy as np

from copy_653.audio import synth, texture, timing
from copy_653.audio.parameters import AudioParameters

TimelineRow = tuple[str, float, float, int, int, str]


def build_exercises_audio(
    exercises: list[str],
    audio_params: AudioParameters,
) -> tuple[np.ndarray, list[TimelineRow]]:
    """Render the audio for a session of exercises and the per-symbol timeline.

    Returns ``(samples, timeline)`` where ``timeline`` is a list of
    ``(symbol, t_on, t_off, exercise_index, word_index, word)`` rows.
    ``t_on`` / ``t_off`` are seconds from the start of the session, so a
    UI consuming these can align display with what is being heard across
    the whole session, not just within one exercise.

    ``exercise_index`` and ``word_index`` are 1-based, matching the
    convention used by :func:`copy_653.audio.synth.compute_word_timeline`.
    """
    if not exercises:
        return np.zeros(0, dtype=np.float32), []

    inter_exercise_seconds = 2 * timing.inter_word_seconds(audio_params)
    parts: list[np.ndarray] = []
    timeline: list[TimelineRow] = []
    cursor = 0.0
    sample_rate = audio_params.sample_rate_hz

    for exercise_index, exercise in enumerate(exercises, start=1):
        if exercise_index > 1:
            silence = synth.synthesize_silence(inter_exercise_seconds, audio_params)
            parts.append(silence)
            cursor += len(silence) / sample_rate

        words = exercise.split(" ")
        exercise_audio = synth.synthesize_words(words, audio_params)
        exercise_timeline = synth.compute_word_timeline(words, audio_params)
        exercise_offset = cursor
        for symbol, t_on_rel, t_off_rel, word_index, word in exercise_timeline:
            timeline.append(
                (
                    symbol,
                    exercise_offset + t_on_rel,
                    exercise_offset + t_off_rel,
                    exercise_index,
                    word_index,
                    word,
                )
            )
        parts.append(exercise_audio)
        cursor += len(exercise_audio) / sample_rate

    samples = np.concatenate(parts).astype(np.float32, copy=False)
    samples = texture.add_receiver_bed(
        samples,
        audio_params,
        context=f"exercises:{len(exercises)}:{'|'.join(exercises)}",
    )
    return samples, timeline
