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
