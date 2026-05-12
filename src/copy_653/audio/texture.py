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
) -> np.ndarray:
    """Mix a very quiet deterministic listening floor under ``samples``."""
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

    mixed = samples.astype(np.float32, copy=False) + floor
    return np.clip(mixed, -1.0, 1.0).astype(np.float32, copy=False)


def _soften_floor(samples: np.ndarray) -> np.ndarray:
    """Shape raw random samples into a less brittle listening bed."""
    kernel = np.array([0.08, 0.18, 0.48, 0.18, 0.08], dtype=np.float32)
    return np.convolve(samples, kernel, mode="same").astype(np.float32)


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
