"""Subtle signal texture helpers for generated CW audio.

The goal is restrained listening presence, not radio-condition simulation.
Tone shape maps to the existing element envelope, receiver bed adds a very
quiet floor, and cadence variation adds tiny deterministic movement to gaps
without changing the configured character rhythm.
"""

from __future__ import annotations

import hashlib
from typing import Final

import numpy as np

from copy_653.audio.parameters import (
    MAX_CADENCE_VARIATION as _MAX_CADENCE_VARIATION,
    MAX_RECEIVER_BED as _MAX_RECEIVER_BED,
    MIN_CADENCE_VARIATION as _MIN_CADENCE_VARIATION,
    MIN_RECEIVER_BED as _MIN_RECEIVER_BED,
    AudioParameters,
)

MIN_TONE_SHAPE: Final = 0
MAX_TONE_SHAPE: Final = 10
MIN_RECEIVER_BED: Final = _MIN_RECEIVER_BED
MAX_RECEIVER_BED: Final = _MAX_RECEIVER_BED
MIN_CADENCE_VARIATION: Final = _MIN_CADENCE_VARIATION
MAX_CADENCE_VARIATION: Final = _MAX_CADENCE_VARIATION
_TONE_SHAPE_SECONDS: Final = (
    0.0,
    0.003,
    0.005,
    0.007,
    0.0085,
    0.010,
    0.011,
    0.012,
    0.013,
    0.014,
    0.015,
)


def envelope_seconds_for_tone_shape(level: int) -> float:
    """Map learner-facing Tone Shape ``0..10`` to envelope ramp seconds."""
    _validate_int_range(level, "tone_shape", MIN_TONE_SHAPE, MAX_TONE_SHAPE)
    return _TONE_SHAPE_SECONDS[level]


def tone_shape_for_envelope_seconds(seconds: float) -> int:
    """Return the nearest learner-facing Tone Shape for a physical ramp value."""
    if seconds < 0:
        raise ValueError(f"envelope_ramp_seconds must be non-negative, got {seconds}")
    distances = [abs(seconds - candidate) for candidate in _TONE_SHAPE_SECONDS]
    return distances.index(min(distances))


def cadence_gap_seconds(
    base_seconds: float,
    params: AudioParameters,
    *,
    gap_index: int,
    context: str,
) -> float:
    """Return a subtly varied gap while preserving the configured timing intent."""
    if params.cadence_variation == 0 or base_seconds <= 0:
        return base_seconds

    max_fraction = params.cadence_variation * 0.006
    offset = _deterministic_unit_interval(
        "cadence",
        context,
        str(gap_index),
        str(params.cadence_variation),
    )
    return base_seconds * (1.0 + ((offset * 2.0) - 1.0) * max_fraction)


def add_receiver_bed(
    samples: np.ndarray,
    params: AudioParameters,
    *,
    context: str,
    dynamic: bool = False,
) -> np.ndarray:
    """Mix a very quiet deterministic listening floor under ``samples``.

    With ``dynamic=False`` (default) the floor RMS is constant across
    the buffer — the existing well-tested behaviour.

    With ``dynamic=True`` the floor amplitude is modulated by a slow
    smoothed random envelope (gear 3 stage 2: scaffold-break dynamic
    floor). The configured ``receiver_bed`` value becomes the *centre*
    of the range rather than the absolute target; the envelope drifts
    around it within ~±2 dB so the floor feels like band conditions
    instead of a static sheet. The envelope is seeded from the same
    context as the noise so replay reproduces the exact modulation.

    The tone itself is never modulated — only the noise floor
    multiplied by the envelope. Bed continuity is preserved end-to-end.
    """
    if params.receiver_bed == 0 or len(samples) == 0:
        return samples.astype(np.float32, copy=False)

    rng = np.random.default_rng(_seed_int("receiver-bed", context, str(params.receiver_bed)))
    floor = rng.standard_normal(len(samples)).astype(np.float32)
    floor = _soften_floor(floor)

    floor_rms = float(np.sqrt(np.mean(np.square(floor), dtype=np.float64)))
    if floor_rms == 0:
        return samples.astype(np.float32, copy=False)

    # Level 1 sits around -48 dB below the tone; level 10 reaches about -35 dB.
    relative_db = -50.0 + (params.receiver_bed * 1.5)
    target_rms = params.amplitude * (10.0 ** (relative_db / 20.0))
    floor = floor * np.float32(target_rms / floor_rms)

    if dynamic:
        envelope = _smooth_random_envelope(
            len(samples),
            sample_rate_hz=params.sample_rate_hz,
            seed=_seed_int("receiver-bed-envelope", context, str(params.receiver_bed)),
        )
        floor = floor * envelope

    mixed = samples.astype(np.float32, copy=False) + floor
    return np.clip(mixed, -1.0, 1.0).astype(np.float32, copy=False)


def _soften_floor(samples: np.ndarray) -> np.ndarray:
    """Shape raw random samples into a less brittle listening bed."""
    kernel = np.array([0.08, 0.18, 0.48, 0.18, 0.08], dtype=np.float32)
    return np.convolve(samples, kernel, mode="same").astype(np.float32)


# Dynamic-floor tunings. The envelope drives the noise floor's level
# over time when ``add_receiver_bed(..., dynamic=True)`` is called.
#
# * _DYNAMIC_FLOOR_RANGE — peak ±deviation around 1.0 in linear gain.
#   ±0.25 corresponds to roughly +1.9 dB / -2.5 dB, which is subtle
#   enough to read as band conditions rather than a fade effect.
# * _DYNAMIC_FLOOR_UPDATE_HZ — rate at which the underlying random
#   walk is sampled. 10 Hz gives a ~5–20s correlation time after the
#   short running average, which feels like slow band drift, not LFO
#   wobble.
# * _DYNAMIC_FLOOR_SMOOTHING — running-average kernel length applied
#   to the low-rate sequence before linear upsampling to audio rate.
_DYNAMIC_FLOOR_RANGE: Final = 0.25
_DYNAMIC_FLOOR_UPDATE_HZ: Final = 10
_DYNAMIC_FLOOR_SMOOTHING: Final = 7


def _smooth_random_envelope(
    n_samples: int,
    *,
    sample_rate_hz: int,
    seed: int,
) -> np.ndarray:
    """Build a slow, smooth, mean-≈1.0 random envelope of length ``n_samples``.

    The envelope is generated at a low rate, smoothed with a short
    running average, tanh-squashed into
    ``[1 - _DYNAMIC_FLOOR_RANGE, 1 + _DYNAMIC_FLOOR_RANGE]``, and
    linearly interpolated up to the audio sample rate. tanh keeps the
    floor strictly bounded without the flat-top artefact a hard clip
    would introduce. The cheap low-rate generation keeps this O(n)
    without scipy.

    ``n_low`` is kept ``>= _DYNAMIC_FLOOR_SMOOTHING`` so the
    ``mode="same"`` convolution returns exactly ``n_low`` samples
    (numpy returns the length of the *longer* input under that mode,
    not the first input).
    """
    if n_samples <= 0:
        return np.ones(0, dtype=np.float32)

    rng = np.random.default_rng(seed)
    seconds = n_samples / float(sample_rate_hz)
    n_low = max(
        _DYNAMIC_FLOOR_SMOOTHING,
        int(np.ceil(seconds * _DYNAMIC_FLOOR_UPDATE_HZ)) + 1,
    )
    raw = rng.standard_normal(n_low).astype(np.float32)
    kernel = np.ones(_DYNAMIC_FLOOR_SMOOTHING, dtype=np.float32) / _DYNAMIC_FLOOR_SMOOTHING
    smoothed = np.convolve(raw, kernel, mode="same").astype(np.float32)
    std = float(smoothed.std())
    if std > 0:
        bounded = np.tanh(smoothed / std).astype(np.float32) * _DYNAMIC_FLOOR_RANGE
    else:
        bounded = np.zeros_like(smoothed)
    centred = 1.0 + bounded
    x_low = np.linspace(0.0, float(n_samples - 1), num=n_low, dtype=np.float64)
    x_high = np.arange(n_samples, dtype=np.float64)
    return np.interp(x_high, x_low, centred).astype(np.float32)


def _validate_int_range(value: int, field: str, minimum: int, maximum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer from {minimum} to {maximum}")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer from {minimum} to {maximum}")


def _deterministic_unit_interval(*parts: str) -> float:
    digest = hashlib.blake2s("|".join(parts).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(2**64 - 1)


def _seed_int(*parts: str) -> int:
    digest = hashlib.blake2s("|".join(parts).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")
