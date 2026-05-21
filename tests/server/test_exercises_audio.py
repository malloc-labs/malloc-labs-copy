"""Regression tests for the Koch Exercises audio assembly.

The load-bearing property exercised here is that the receiver bed is
mixed over the *whole* session buffer rather than per-exercise: the
inter-exercise silence window must carry the same floor as the
exercise audio, otherwise the level dip becomes an audible "exercise
ended" marker on headphones or decent speakers.
"""

from __future__ import annotations

import numpy as np

from copy_653.audio import synth, timing
from copy_653.audio.parameters import AudioParameters
from copy_653.server.exercises_audio import build_exercises_audio


def _inter_exercise_window(audio_params: AudioParameters, first_exercise: str) -> tuple[int, int]:
    """Return (start, end) sample indices of the first inter-exercise silence."""
    first_audio = synth.synthesize_words(first_exercise.split(" "), audio_params)
    silence = synth.synthesize_silence(2 * timing.inter_word_seconds(audio_params), audio_params)
    return len(first_audio), len(first_audio) + len(silence)


def test_inter_exercise_gap_carries_receiver_bed_when_enabled():
    exercises = ["K M", "M K"]
    params = AudioParameters(
        character_speed_wpm=20,
        effective_speed_wpm=20,
        receiver_bed=2,
        cadence_variation=0,
    )
    samples, _ = build_exercises_audio(exercises, params)
    start, end = _inter_exercise_window(params, exercises[0])

    # Trim a handful of samples either side to absorb rounding inside
    # synthesize_silence; the interior must still be non-silent.
    inner = samples[start + 8 : end - 8]
    rms = float(np.sqrt(np.mean(np.square(inner.astype(np.float64)))))
    assert rms > 1e-5, "inter-exercise silence should carry the receiver bed"


def test_inter_exercise_gap_silent_when_bed_disabled():
    exercises = ["K M", "M K"]
    params = AudioParameters(
        character_speed_wpm=20,
        effective_speed_wpm=20,
        receiver_bed=0,
        cadence_variation=0,
    )
    samples, _ = build_exercises_audio(exercises, params)
    start, end = _inter_exercise_window(params, exercises[0])

    inner = samples[start + 8 : end - 8]
    assert np.all(inner == 0.0)
