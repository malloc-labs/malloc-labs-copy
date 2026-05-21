"""Tests for subtle CW signal texture helpers."""

import math

import numpy as np

from copy_653.audio import texture
from copy_653.audio.parameters import AudioParameters


def test_tone_shape_maps_current_default_envelope_to_level_two():
    assert texture.tone_shape_for_envelope_seconds(0.005) == 2
    assert texture.envelope_seconds_for_tone_shape(2) == 0.005


def test_tone_shape_zero_disables_envelope_ramp():
    assert texture.envelope_seconds_for_tone_shape(0) == 0.0


def test_cadence_gap_zero_level_returns_base_gap():
    params = AudioParameters(cadence_variation=0)
    assert texture.cadence_gap_seconds(0.5, params, gap_index=0, context="km") == 0.5


def test_cadence_gap_variation_is_bounded_and_deterministic():
    params = AudioParameters(cadence_variation=5)

    first = texture.cadence_gap_seconds(0.5, params, gap_index=3, context="km")
    second = texture.cadence_gap_seconds(0.5, params, gap_index=3, context="km")

    assert first == second
    assert math.isclose(first, 0.5, rel_tol=0.03)


def test_receiver_bed_zero_level_returns_samples_without_copy():
    params = AudioParameters(receiver_bed=0)
    samples = np.zeros(128, dtype=np.float32)

    textured = texture.add_receiver_bed(samples, params, context="km")

    assert textured is samples


def test_receiver_bed_adds_deterministic_quiet_floor():
    params = AudioParameters(receiver_bed=2)
    samples = np.zeros(1024, dtype=np.float32)

    first = texture.add_receiver_bed(samples, params, context="km")
    second = texture.add_receiver_bed(samples, params, context="km")

    np.testing.assert_array_equal(first, second)
    assert first.dtype == np.float32
    assert np.any(first != 0.0)
    assert np.max(np.abs(first)) < 0.01


# ---- Gear 3 stage 2: dynamic floor -----------------------------------------


def test_receiver_bed_dynamic_default_is_static():
    # Default add_receiver_bed call (dynamic kwarg omitted) must
    # produce exactly the static-floor output we tested above. This
    # is the back-compat guarantee for every existing caller.
    params = AudioParameters(receiver_bed=2, sample_rate_hz=48_000)
    samples = np.zeros(48_000, dtype=np.float32)

    static = texture.add_receiver_bed(samples, params, context="km")
    explicit_static = texture.add_receiver_bed(samples, params, context="km", dynamic=False)
    np.testing.assert_array_equal(static, explicit_static)


def test_receiver_bed_dynamic_modulates_rms_over_time():
    # With a long enough buffer the RMS in two well-separated windows
    # should noticeably differ — the floor is breathing, not flat.
    params = AudioParameters(receiver_bed=4, sample_rate_hz=48_000)
    # 20 s of silence → plenty of room for the envelope to drift.
    samples = np.zeros(20 * 48_000, dtype=np.float32)

    dynamic = texture.add_receiver_bed(samples, params, context="km", dynamic=True)
    window = 48_000  # 1 s
    early_rms = float(np.sqrt(np.mean(np.square(dynamic[:window].astype(np.float64)))))
    late_rms = float(np.sqrt(np.mean(np.square(dynamic[-window:].astype(np.float64)))))
    # The static-floor RMS is a known reference; the dynamic windows
    # should diverge from each other by a perceptible margin.
    assert early_rms > 0 and late_rms > 0
    assert abs(early_rms - late_rms) / max(early_rms, late_rms) > 0.05


def test_receiver_bed_dynamic_is_deterministic_with_same_context():
    params = AudioParameters(receiver_bed=2, sample_rate_hz=48_000)
    samples = np.zeros(48_000, dtype=np.float32)

    first = texture.add_receiver_bed(samples, params, context="km", dynamic=True)
    second = texture.add_receiver_bed(samples, params, context="km", dynamic=True)
    np.testing.assert_array_equal(first, second)


def test_receiver_bed_dynamic_changes_with_context():
    # A different context string drives a different envelope seed, so
    # the rendered floor must differ (otherwise the envelope is
    # accidentally context-independent).
    params = AudioParameters(receiver_bed=2, sample_rate_hz=48_000)
    samples = np.zeros(48_000, dtype=np.float32)

    a = texture.add_receiver_bed(samples, params, context="exercises:a", dynamic=True)
    b = texture.add_receiver_bed(samples, params, context="exercises:b", dynamic=True)
    assert not np.array_equal(a, b)


def test_receiver_bed_dynamic_envelope_stays_in_bounded_range():
    # The envelope itself is what we want to bound — its values must
    # stay close to 1.0 so the floor is modulated, not silenced or
    # blown up. We probe the helper directly to assert that contract.
    envelope = texture._smooth_random_envelope(
        n_samples=48_000 * 30,
        sample_rate_hz=48_000,
        seed=0xCAFE,
    )
    # _DYNAMIC_FLOOR_RANGE is the strict tanh-squashed bound on the
    # envelope in either direction (tiny slack for float rounding on
    # interpolation).
    assert envelope.min() > 1.0 - texture._DYNAMIC_FLOOR_RANGE - 1e-3
    assert envelope.max() < 1.0 + texture._DYNAMIC_FLOOR_RANGE + 1e-3
    # Mean should be close to 1.0 over a long buffer (zero-mean
    # smoothed noise translated up).
    assert abs(float(envelope.mean()) - 1.0) < 0.05


def test_smooth_random_envelope_short_buffer_safe():
    # A tiny buffer should not crash. The "low rate" inner buffer
    # also caps at n_low >= 2.
    envelope = texture._smooth_random_envelope(
        n_samples=8,
        sample_rate_hz=48_000,
        seed=1,
    )
    assert len(envelope) == 8
    assert envelope.dtype == np.float32
