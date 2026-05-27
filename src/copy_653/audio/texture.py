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


def distortion_for_tone_shape(level: int) -> float:
    """Map Tone Shape ``0..10`` to tone_distortion (0.0..1.0).

    Level 10 (cleanest) = 0.0; level 0 (roughest) = 0.8.
    """
    _validate_int_range(level, "tone_shape", MIN_TONE_SHAPE, MAX_TONE_SHAPE)
    return max(0.0, min(1.0, (10 - level) * 0.08))


def ripple_for_tone_shape(level: int) -> float:
    """Map Tone Shape ``0..10`` to tone_ripple (0.0..1.0).

    Engages below level 5; level 0 = 0.7 (deep hum).
    """
    _validate_int_range(level, "tone_shape", MIN_TONE_SHAPE, MAX_TONE_SHAPE)
    if level >= 5:
        return 0.0
    return max(0.0, min(1.0, (5 - level) * 0.14))


def tone_shape_for_envelope_seconds(seconds: float) -> int:
    """Return the nearest learner-facing Tone Shape for a physical ramp value."""
    if seconds < 0:
        raise ValueError(f"envelope_ramp_seconds must be non-negative, got {seconds}")
    distances = [abs(seconds - candidate) for candidate in _TONE_SHAPE_SECONDS]
    return distances.index(min(distances))


def envelope_seconds_for_rst_tone(t: int) -> float:
    """Map an RST Tone value (1..9) to envelope ramp seconds.

    Goes through the Tone Shape lookup so the per-exercise audio render
    stays on the same physical scale as the configured baseline; the
    UI's 1..9 → 0..10 conversion is linear-rounded (see settings.js).
    """
    _validate_rst_tone(t)
    tone_shape = max(MIN_TONE_SHAPE, min(MAX_TONE_SHAPE, round((t - 1) * 10 / 8)))
    return _TONE_SHAPE_SECONDS[tone_shape]


def distortion_for_rst_tone(t: int) -> float:
    """Map an RST Tone value (1..9) to tone_distortion (0.0..1.0).

    T9 = 0.0 (pure sine), T1 = 0.8 (heavily clipped, buzzy).
    The curve is linear; T5 sits at ~0.4.
    """
    _validate_rst_tone(t)
    return max(0.0, min(1.0, (9 - t) * 0.1))


def ripple_for_rst_tone(t: int) -> float:
    """Map an RST Tone value (1..9) to tone_ripple (0.0..1.0).

    T9 = 0.0 (steady tone), T1 = 0.7 (deep AC-hum modulation).
    Engages below T6 so the upper half of the scale stays clean.
    """
    _validate_rst_tone(t)
    if t >= 6:
        return 0.0
    return max(0.0, min(1.0, (6 - t) * 0.14))


def _validate_rst_tone(t: int) -> None:
    if not isinstance(t, int) or isinstance(t, bool):
        raise ValueError(f"rst tone must be an integer 1..9, got {t!r}")
    if not 1 <= t <= 9:
        raise ValueError(f"rst tone must be in 1..9, got {t}")


def bed_level_for_rst_strength(s: int | float) -> float:
    """Map an RST Strength value (1..9) to a (fractional) bed level (0..10).

    Inverted (higher S = lower bed), linear, matches the UI conversion.
    Returned as a float so the audio envelope can carry continuous
    cross-fades between integer S values without quantisation steps.
    """
    s_clamped = max(1.0, min(9.0, float(s)))
    return (9.0 - s_clamped) * 10.0 / 8.0


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
    level_schedule: list[tuple[int, int, float]] | None = None,
) -> np.ndarray:
    """Mix a very quiet deterministic listening floor under ``samples``.

    With ``dynamic=False`` and no ``level_schedule`` (default) the floor
    RMS is constant across the buffer.

    With ``dynamic=True`` the floor amplitude is modulated by a slow
    smoothed random envelope (gear 3 stage 2: scaffold-break dynamic
    floor). The configured ``receiver_bed`` becomes the *centre* of
    the range; the envelope drifts around it within ~±2 dB so the
    floor feels like band conditions instead of a static sheet.

    With ``level_schedule`` (gear 3 RST sub-axis) the floor target is
    piecewise: each ``(start_sample, end_sample, bed_level)`` segment
    is held flat at its level, and the gaps between adjacent segments
    cross-fade linearly in dB. Segments may overlap or share endpoints;
    the last value written wins for any shared sample. Suppresses
    ``dynamic`` since the schedule itself is the (now deterministic)
    band-conditions envelope.

    Constant-loudness normalisation keeps the total perceived volume
    stable regardless of bed level — the signal attenuates as the
    floor rises so the learner's headphone volume stays safe. This
    mirrors real-radio AGC: the noise is the constant, the signal
    fades.

    Bed continuity is preserved end-to-end.
    """
    if len(samples) == 0:
        return samples.astype(np.float32, copy=False)
    if level_schedule is None and params.receiver_bed == 0:
        return samples.astype(np.float32, copy=False)

    rng = np.random.default_rng(_seed_int("receiver-bed", context, str(params.receiver_bed)))
    floor = rng.standard_normal(len(samples)).astype(np.float32)
    floor = _soften_floor(floor)

    floor_rms = float(np.sqrt(np.mean(np.square(floor), dtype=np.float64)))
    if floor_rms == 0:
        return samples.astype(np.float32, copy=False)
    floor = (floor / np.float32(floor_rms)).astype(np.float32)

    if level_schedule is not None:
        target_rms = _build_bed_target_rms_envelope(len(samples), params.amplitude, level_schedule)
    else:
        relative_db = -50.0 + (params.receiver_bed * 4.4)
        target_rms_value = params.amplitude * (10.0 ** (relative_db / 20.0))
        target_rms = np.full(len(samples), target_rms_value, dtype=np.float32)

    # Constant-loudness gain: signal_gain = 1/sqrt(1 + ratio²) where
    # ratio = noise_rms / signal_amplitude. Computed from the static
    # target_rms so dynamic-floor drift (±2 dB) passes through as
    # natural band-condition variation rather than being flattened.
    ratio = target_rms / np.float32(params.amplitude)
    loudness_gain = (1.0 / np.sqrt(1.0 + ratio * ratio)).astype(np.float32)

    floor = (floor * target_rms).astype(np.float32)

    if dynamic and level_schedule is None:
        envelope = _smooth_random_envelope(
            len(samples),
            sample_rate_hz=params.sample_rate_hz,
            seed=_seed_int("receiver-bed-envelope", context, str(params.receiver_bed)),
        )
        floor = floor * envelope

    mixed = (samples.astype(np.float32, copy=False) + floor) * loudness_gain
    return np.clip(mixed, -1.0, 1.0).astype(np.float32, copy=False)


def _bed_level_to_relative_db(bed_level: float) -> float:
    """Inverse of the constant-bed relative_db formula, accepting floats."""
    return -50.0 + (float(bed_level) * 4.4)


def _build_bed_target_rms_envelope(
    n_samples: int,
    amplitude: float,
    schedule: list[tuple[int, int, float]],
) -> np.ndarray:
    """Per-sample bed target RMS, linearly interpolated in dB across gaps.

    Each schedule entry ``(start, end, bed_level)`` holds the target at
    that level across ``[start, end)``. Adjacent entries with a gap
    have the dB ramp written across the gap; before the first segment
    and after the last, the envelope is clamped to the nearest
    segment's level so leading silence and trailing buffer get a
    consistent floor.
    """
    if n_samples <= 0 or not schedule:
        return np.zeros(max(0, n_samples), dtype=np.float32)

    db_envelope = np.zeros(n_samples, dtype=np.float32)
    sorted_segments = sorted(schedule, key=lambda seg: seg[0])

    first_start, _, first_level = sorted_segments[0]
    _, last_end, last_level = sorted_segments[-1]
    db_envelope[: max(0, first_start)] = _bed_level_to_relative_db(first_level)
    db_envelope[min(n_samples, last_end) :] = _bed_level_to_relative_db(last_level)

    for start, end, level in sorted_segments:
        lo = max(0, min(n_samples, start))
        hi = max(lo, min(n_samples, end))
        db_envelope[lo:hi] = _bed_level_to_relative_db(level)

    for prev_seg, next_seg in zip(sorted_segments, sorted_segments[1:]):
        prev_end = prev_seg[1]
        next_start = next_seg[0]
        if next_start <= prev_end:
            continue
        ramp_lo = max(0, min(n_samples, prev_end))
        ramp_hi = max(ramp_lo, min(n_samples, next_start))
        if ramp_hi <= ramp_lo:
            continue
        db_envelope[ramp_lo:ramp_hi] = np.linspace(
            _bed_level_to_relative_db(prev_seg[2]),
            _bed_level_to_relative_db(next_seg[2]),
            num=ramp_hi - ramp_lo,
            dtype=np.float32,
        )

    target_rms = float(amplitude) * np.power(10.0, db_envelope / 20.0, dtype=np.float32)
    return target_rms.astype(np.float32)


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
