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
    samples, _, _ = build_exercises_audio(exercises, params)
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
    samples, _, _ = build_exercises_audio(exercises, params)
    start, end = _inter_exercise_window(params, exercises[0])

    inner = samples[start + 8 : end - 8]
    assert np.all(inner == 0.0)


# ---- Gear 3 stage 1: scaffold-break lead-in --------------------------------


def test_scaffold_break_off_by_default():
    # Default call shape is unchanged: no lead-in silence, audio_shape
    # reports the feature as off and an empty list of lead-ins.
    exercises = ["DE K M", "DE M K"]
    params = AudioParameters(
        character_speed_wpm=20,
        effective_speed_wpm=20,
        receiver_bed=0,
        cadence_variation=0,
    )
    samples_off, _, shape_off = build_exercises_audio(exercises, params)
    samples_default, _, shape_default = build_exercises_audio(
        exercises, params, scaffold_break=False
    )
    assert shape_off == shape_default
    assert shape_off["scaffold_break"] == {
        "enabled": False,
        "lead_in_seconds": [],
        "dynamic_floor": False,
    }
    assert len(samples_off) == len(samples_default)


def test_scaffold_break_flags_dynamic_floor_on():
    # Gear 3 stage 2: with scaffold_break on, the audio_shape records
    # that the dynamic floor was engaged so a session record can
    # reproduce the exact audio later. The bed itself is exercised
    # in tests/audio/test_texture.py.
    exercises = ["DE K M"]
    params = AudioParameters(receiver_bed=4)
    _, _, shape = build_exercises_audio(exercises, params, scaffold_break=True, rng_seed=1)
    assert shape["scaffold_break"]["dynamic_floor"] is True


def test_scaffold_break_inserts_lead_in_per_exercise():
    exercises = ["DE K M", "DE M K", "DE K"]
    params = AudioParameters(
        character_speed_wpm=20,
        effective_speed_wpm=20,
        receiver_bed=0,
        cadence_variation=0,
    )
    _, timeline, shape = build_exercises_audio(exercises, params, scaffold_break=True, rng_seed=42)

    lead_ins = shape["scaffold_break"]["lead_in_seconds"]
    assert shape["scaffold_break"]["enabled"] is True
    assert len(lead_ins) == len(exercises)
    for value in lead_ins:
        # Drawn from SCAFFOLD_BREAK_LEAD_IN_RANGE_SECONDS = (2.0, 10.0).
        assert 2.0 <= value <= 10.0

    # The first symbol (D of DE) should now land *after* the first
    # lead-in silence — the load-bearing claim of the scaffold-break
    # probe is that DE is no longer pinned to t=0.
    first_symbol_t_on = timeline[0][1]
    assert first_symbol_t_on >= lead_ins[0] - 0.01


def test_scaffold_break_is_deterministic_with_seed():
    # Same seed → same lead-ins → same audio buffer length and same
    # timeline offsets. This is what makes session replay safe.
    exercises = ["DE K M", "DE M K"]
    params = AudioParameters(
        character_speed_wpm=20,
        effective_speed_wpm=20,
        receiver_bed=0,
        cadence_variation=0,
    )
    s1, t1, shape1 = build_exercises_audio(exercises, params, scaffold_break=True, rng_seed=7)
    s2, t2, shape2 = build_exercises_audio(exercises, params, scaffold_break=True, rng_seed=7)
    assert shape1 == shape2
    assert len(s1) == len(s2)
    assert t1 == t2

    # And a different seed reliably produces a different lead-in
    # sequence (uniform draws on a continuous range collide with
    # vanishing probability).
    _, _, shape3 = build_exercises_audio(exercises, params, scaffold_break=True, rng_seed=8)
    assert (
        shape3["scaffold_break"]["lead_in_seconds"] != shape1["scaffold_break"]["lead_in_seconds"]
    )


def test_scaffold_break_requires_rng_seed_when_enabled():
    exercises = ["DE K M"]
    params = AudioParameters()
    try:
        build_exercises_audio(exercises, params, scaffold_break=True, rng_seed=None)
    except ValueError as exc:
        assert "rng_seed" in str(exc)
    else:
        raise AssertionError("scaffold_break=True without rng_seed should raise ValueError")


def test_scaffold_break_empty_exercises_short_circuits_safely():
    # Empty input early-returns before any lead-in draw. The shape
    # honestly reports what was *requested* (enabled=True) with an
    # empty list of lead-ins — there was nothing to apply it to.
    samples, timeline, shape = build_exercises_audio(
        [], AudioParameters(), scaffold_break=True, rng_seed=42
    )
    assert len(samples) == 0
    assert timeline == []
    assert shape["scaffold_break"] == {
        "enabled": True,
        "lead_in_seconds": [],
        "dynamic_floor": True,
    }
