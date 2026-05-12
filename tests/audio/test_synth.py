"""Tests for copy_653.audio.synth."""

import math

import numpy as np

from copy_653.audio import synth, timing
from copy_653.audio.parameters import AudioParameters


def test_generate_tone_has_expected_sample_count():
    params = AudioParameters(sample_rate_hz=48_000)
    samples = synth.generate_tone(duration_seconds=0.1, params=params)
    # 0.1 s × 48 kHz = 4800 samples.
    assert len(samples) == 4800


def test_generate_tone_is_float32():
    params = AudioParameters()
    samples = synth.generate_tone(0.05, params)
    assert samples.dtype == np.float32


def test_generate_tone_amplitude_within_unit_range():
    params = AudioParameters()
    samples = synth.generate_tone(0.05, params)
    assert samples.max() <= 1.0
    assert samples.min() >= -1.0


def test_generate_tone_default_amplitude_is_quiet():
    # Default amplitude is 0.3 (≈ -10 dB FS) for hearing safety.
    # Peak of the generated sine should sit at that level, not full-scale.
    params = AudioParameters()
    samples = synth.generate_tone(0.05, params)
    assert math.isclose(samples.max(), 0.3, abs_tol=1e-3)
    assert math.isclose(samples.min(), -0.3, abs_tol=1e-3)


def test_generate_tone_respects_configured_amplitude():
    # A configured amplitude is honoured exactly (within the discretisation
    # of the sine over the duration's worth of samples).
    params = AudioParameters(amplitude=0.5)
    samples = synth.generate_tone(0.05, params)
    assert math.isclose(samples.max(), 0.5, abs_tol=1e-3)
    assert math.isclose(samples.min(), -0.5, abs_tol=1e-3)


def test_apply_envelope_starts_and_ends_at_zero():
    params = AudioParameters()
    samples = synth.generate_tone(0.05, params)
    enveloped = synth.apply_envelope(samples, params)
    # Raised-cosine starts at exactly 0 and ends at exactly 0.
    assert enveloped[0] == 0.0
    assert enveloped[-1] == 0.0


def test_apply_envelope_preserves_centre_amplitude():
    # Past the ramp region, the envelope is 1.0 — middle samples are
    # unchanged from the input.
    params = AudioParameters(sample_rate_hz=48_000, envelope_ramp_seconds=0.005)
    samples = np.ones(4_800, dtype=np.float32)  # 100 ms of ones
    enveloped = synth.apply_envelope(samples, params)
    middle = len(enveloped) // 2
    assert enveloped[middle] == 1.0


def test_apply_envelope_does_not_mutate_input():
    params = AudioParameters()
    samples = synth.generate_tone(0.05, params)
    original = samples.copy()
    synth.apply_envelope(samples, params)
    np.testing.assert_array_equal(samples, original)


def test_synthesize_element_dah_is_three_times_dit():
    params = AudioParameters()
    dit = synth.synthesize_element(is_dah=False, params=params)
    dah = synth.synthesize_element(is_dah=True, params=params)
    # 3:1 sample ratio (sample-quantization may produce ±1 difference).
    assert abs(len(dah) - 3 * len(dit)) <= 1


def test_synthesize_silence_is_all_zeros():
    params = AudioParameters()
    silence = synth.synthesize_silence(0.1, params)
    assert silence.dtype == np.float32
    assert np.all(silence == 0.0)


def test_synthesize_symbol_k_has_expected_length():
    # K = -.- → 3 elements (dah, dit, dah) + 2 inter-element gaps.
    params = AudioParameters()
    samples = synth.synthesize_symbol("K", params)
    expected_seconds = (
        timing.dah_seconds(20)
        + timing.dit_seconds(20)
        + timing.dah_seconds(20)
        + 2 * timing.inter_element_seconds(20)
    )
    expected_samples = int(round(expected_seconds * 48_000))
    # ±2 samples for rounding inside synthesize_silence/element.
    assert abs(len(samples) - expected_samples) <= 2


def test_synthesize_sequence_separates_with_inter_character_silence():
    # Two K's separated by inter-character silence.
    params = AudioParameters(character_speed_wpm=20, effective_speed_wpm=20)
    one = synth.synthesize_symbol("K", params)
    two = synth.synthesize_sequence(["K", "K"], params)
    inter_char_samples = int(round(timing.inter_character_seconds(params) * 48_000))
    expected = 2 * len(one) + inter_char_samples
    assert abs(len(two) - expected) <= 2


def test_synthesize_sequence_adds_receiver_bed_when_configured():
    clean = synth.synthesize_sequence(["K"], AudioParameters(receiver_bed=0))
    textured = synth.synthesize_sequence(["K"], AudioParameters(receiver_bed=2))

    assert textured.dtype == np.float32
    assert len(textured) == len(clean)
    assert not np.array_equal(textured, clean)
    assert textured.max() <= 1.0
    assert textured.min() >= -1.0


def test_synthesize_sequence_cadence_variation_changes_gap_without_symbol_shape():
    clean_params = AudioParameters(character_speed_wpm=20, effective_speed_wpm=20)
    varied_params = AudioParameters(
        character_speed_wpm=20,
        effective_speed_wpm=20,
        cadence_variation=5,
    )

    one = synth.synthesize_symbol("K", clean_params)
    clean = synth.synthesize_sequence(["K", "K"], clean_params)
    varied = synth.synthesize_sequence(["K", "K"], varied_params)

    assert len(varied) != len(clean)
    assert np.array_equal(varied[: len(one)], clean[: len(one)])


def test_synthesize_sequence_empty_returns_empty_buffer():
    params = AudioParameters()
    result = synth.synthesize_sequence([], params)
    assert len(result) == 0
    assert result.dtype == np.float32


def test_symbol_duration_matches_synthesised_length():
    params = AudioParameters(character_speed_wpm=20, effective_speed_wpm=20)
    samples = synth.synthesize_symbol("K", params)
    duration = synth.symbol_duration_seconds("K", params)
    expected_samples = int(round(duration * params.sample_rate_hz))
    assert abs(len(samples) - expected_samples) <= 2


def test_compute_timeline_empty():
    assert synth.compute_timeline([], AudioParameters()) == []


def test_compute_timeline_single_symbol_starts_at_zero():
    params = AudioParameters(character_speed_wpm=20, effective_speed_wpm=20)
    timeline = synth.compute_timeline(["K"], params)
    assert len(timeline) == 1
    symbol, t_on, t_off = timeline[0]
    assert symbol == "K"
    assert t_on == 0.0
    assert t_off == synth.symbol_duration_seconds("K", params)


def test_compute_timeline_inter_character_gap_with_farnsworth():
    # Farnsworth: characters render at 25 WPM, but spacing widens to
    # hit a 10 WPM effective rate. The gap between symbols 0 and 1
    # should match inter_character_seconds (which honours Farnsworth).
    params = AudioParameters(character_speed_wpm=25, effective_speed_wpm=10)
    timeline = synth.compute_timeline(["K", "M"], params)
    assert len(timeline) == 2
    _, _, t_off_first = timeline[0]
    _, t_on_second, _ = timeline[1]
    gap = t_on_second - t_off_first
    assert math.isclose(gap, timing.inter_character_seconds(params), abs_tol=1e-9)


def test_synthesize_words_separates_words_with_inter_word_silence():
    params = AudioParameters(character_speed_wpm=20, effective_speed_wpm=20)
    word_audio = synth.synthesize_words(["km", "u"], params)
    expected_seconds = (
        synth.symbol_duration_seconds("K", params)
        + timing.inter_character_seconds(params)
        + synth.symbol_duration_seconds("M", params)
        + timing.inter_word_seconds(params)
        + synth.symbol_duration_seconds("U", params)
    )
    expected_samples = int(round(expected_seconds * params.sample_rate_hz))
    assert abs(len(word_audio) - expected_samples) <= 4


def test_compute_word_timeline_records_word_index_and_gap():
    params = AudioParameters(character_speed_wpm=20, effective_speed_wpm=20)
    timeline = synth.compute_word_timeline(["km", "u"], params)

    assert timeline[0][0] == "K"
    assert timeline[0][3:] == (1, "km")
    assert timeline[1][0] == "M"
    assert timeline[1][3:] == (1, "km")
    assert timeline[2][0] == "U"
    assert timeline[2][3:] == (2, "u")

    gap_inside_word = timeline[1][1] - timeline[0][2]
    gap_between_words = timeline[2][1] - timeline[1][2]
    assert math.isclose(gap_inside_word, timing.inter_character_seconds(params), abs_tol=1e-9)
    assert math.isclose(gap_between_words, timing.inter_word_seconds(params), abs_tol=1e-9)
