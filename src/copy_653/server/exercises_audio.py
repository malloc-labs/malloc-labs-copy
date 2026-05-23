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

Scaffold-break (gear 3): when ``scaffold_break`` is enabled the
assembler applies two probes intended to disrupt the scaffolding
the early-Koch learner has built up around exercise structure:

* Stage 1 (lead-in): prepend a per-exercise random lead-in silence
  (drawn from :data:`SCAFFOLD_BREAK_LEAD_IN_RANGE_SECONDS`) before
  each exercise. DE is still the first word of the exercise string
  but no longer lands at the same offset each time, so the learner
  cannot use "DE arriving now" as a reliable start-of-exercise
  marker.
* Stage 2 (dynamic floor): pass ``dynamic=True`` to
  :func:`copy_653.audio.texture.add_receiver_bed` so the noise
  floor amplitude is modulated by a slow smoothed random envelope
  across the whole assembled buffer — the floor feels like band
  conditions rather than a static sheet.

Both engage once every burden band reaches ``MAX_GEAR`` and disengage
only when a band drops out — tracking the gear axis's own hysteresis
rather than the more volatile next-symbol evidence signal.

This module is pure: no I/O, no clock, no module-level random state.
The WebSocket server decides when to start a session and how to emit
events; this module decides what audio buffer and symbol schedule the
learner hears.
"""

from __future__ import annotations

from dataclasses import replace
from random import Random
from typing import Any

import numpy as np

from copy_653.audio import synth, texture, timing
from copy_653.audio.parameters import AudioParameters

TimelineRow = tuple[str, float, float, int, int, str]

# Per-exercise lead-in silence range when scaffold_break is on. Picked
# to be subtle enough that the session does not feel padded while still
# breaking the "DE at t=0" reflex.
SCAFFOLD_BREAK_LEAD_IN_RANGE_SECONDS: tuple[float, float] = (2.0, 10.0)


def build_exercises_audio(
    exercises: list[str],
    audio_params: AudioParameters,
    *,
    scaffold_break: bool = False,
    rng_seed: int | None = None,
    rst_draws: list[tuple[int | None, int | None]] | None = None,
) -> tuple[np.ndarray, list[TimelineRow], dict[str, Any]]:
    """Render the audio for a session of exercises and the per-symbol timeline.

    Returns ``(samples, timeline, audio_shape)`` where ``timeline`` is a
    list of ``(symbol, t_on, t_off, exercise_index, word_index, word)``
    rows. ``t_on`` / ``t_off`` are seconds from the start of the session,
    so a UI consuming these can align display with what is being heard
    across the whole session, not just within one exercise.

    ``exercise_index`` and ``word_index`` are 1-based, matching the
    convention used by :func:`copy_653.audio.synth.compute_word_timeline`.

    ``scaffold_break`` toggles gear 3 stage 1: per-exercise random
    lead-in silence to disrupt the "DE at t=0" reflex. ``rng_seed`` is
    used to seed the per-call ``Random`` so the same seed reproduces the
    same lead-ins (replay-safe). ``rng_seed`` is required when
    ``scaffold_break`` is true; otherwise it is ignored.

    ``audio_shape`` captures the assembly-time choices that the seed
    governs (``lead_in_seconds`` per exercise) so the session record can
    reproduce the exact audio later. When ``scaffold_break`` is off the
    dict reports ``enabled: false`` and an empty list.
    """
    rst_active = rst_draws is not None and any(s is not None or t is not None for s, t in rst_draws)
    audio_shape: dict[str, Any] = {
        "scaffold_break": {
            "enabled": bool(scaffold_break),
            "lead_in_seconds": [],
            # RST sub-axis supersedes the random dynamic floor — per-exercise
            # S targets are a more structured version of the same idea.
            "dynamic_floor": bool(scaffold_break) and not rst_active,
        }
    }

    if not exercises:
        return np.zeros(0, dtype=np.float32), [], audio_shape

    if scaffold_break and rng_seed is None:
        raise ValueError("scaffold_break=True requires rng_seed to be provided")

    if rst_draws is not None and len(rst_draws) != len(exercises):
        raise ValueError(
            "rst_draws length must match exercises length, "
            f"got rst_draws={len(rst_draws)} exercises={len(exercises)}"
        )

    rng = Random(rng_seed) if scaffold_break else None
    lead_in_min, lead_in_max = SCAFFOLD_BREAK_LEAD_IN_RANGE_SECONDS

    inter_exercise_seconds = 2 * timing.inter_word_seconds(audio_params)
    parts: list[np.ndarray] = []
    timeline: list[TimelineRow] = []
    cursor = 0.0
    sample_rate = audio_params.sample_rate_hz
    lead_ins: list[float] = []
    # Each entry is (start_sample, end_sample, bed_level) for the exercise
    # audio region only. Lead-in / inter-exercise silence is the cross-fade
    # gap between adjacent entries.
    bed_schedule: list[tuple[int, int, float]] = []

    for exercise_index, exercise in enumerate(exercises, start=1):
        if exercise_index > 1:
            silence = synth.synthesize_silence(inter_exercise_seconds, audio_params)
            parts.append(silence)
            cursor += len(silence) / sample_rate

        if rng is not None:
            lead_in_seconds = rng.uniform(lead_in_min, lead_in_max)
            lead_in = synth.synthesize_silence(lead_in_seconds, audio_params)
            parts.append(lead_in)
            cursor += len(lead_in) / sample_rate
            lead_ins.append(lead_in_seconds)

        words = exercise.split(" ")
        exercise_params = _params_for_exercise(audio_params, rst_draws, exercise_index)
        exercise_audio = synth.synthesize_words(words, exercise_params)
        exercise_timeline = synth.compute_word_timeline(words, exercise_params)
        exercise_offset = cursor
        exercise_start_sample = int(round(exercise_offset * sample_rate))
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

        if rst_active:
            bed_schedule.append(
                (
                    exercise_start_sample,
                    exercise_start_sample + len(exercise_audio),
                    _bed_level_for_exercise(audio_params, rst_draws, exercise_index),
                )
            )

    samples = np.concatenate(parts).astype(np.float32, copy=False)
    samples = texture.add_receiver_bed(
        samples,
        audio_params,
        context=f"exercises:{len(exercises)}:{'|'.join(exercises)}",
        dynamic=scaffold_break and not rst_active,
        level_schedule=bed_schedule if rst_active else None,
    )
    audio_shape["scaffold_break"]["lead_in_seconds"] = lead_ins
    return samples, timeline, audio_shape


def _params_for_exercise(
    audio_params: AudioParameters,
    rst_draws: list[tuple[int | None, int | None]] | None,
    exercise_index: int,
) -> AudioParameters:
    """Per-exercise AudioParameters override for the T sub-axis.

    Returns the same instance when no T override applies so the
    common case skips a dataclass copy.
    """
    if rst_draws is None:
        return audio_params
    if not 1 <= exercise_index <= len(rst_draws):
        return audio_params
    _, t = rst_draws[exercise_index - 1]
    if t is None:
        return audio_params
    return replace(audio_params, envelope_ramp_seconds=texture.envelope_seconds_for_rst_tone(t))


def _bed_level_for_exercise(
    audio_params: AudioParameters,
    rst_draws: list[tuple[int | None, int | None]] | None,
    exercise_index: int,
) -> float:
    """Per-exercise bed level (float, may be fractional) for the S sub-axis.

    Falls back to the configured ``receiver_bed`` when there's no S
    override for this exercise — keeps mixed sessions (some bands at
    gear 3, others below) feeling like a single coherent floor that
    just drifts up or down at the gear-3 bands.
    """
    if rst_draws is None or not 1 <= exercise_index <= len(rst_draws):
        return float(audio_params.receiver_bed)
    s, _ = rst_draws[exercise_index - 1]
    if s is None:
        return float(audio_params.receiver_bed)
    return texture.bed_level_for_rst_strength(s)
