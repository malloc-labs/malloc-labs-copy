"""Tests for Word Detection server-side audio assembly."""

import math

import numpy as np

from copy_653.audio import synth, timing
from copy_653.audio.parameters import AudioParameters
from copy_653.server import word_detection_audio
from copy_653.server.word_detection_audio import (
    build_word_detection_audio,
    instruction_symbols_for_word,
)


def test_instruction_symbols_are_limited_to_focus_letters():
    assert instruction_symbols_for_word("make", frozenset({"K", "M"})) == ("M", "K")
    assert instruction_symbols_for_word("make", frozenset({"U"})) == ()


def test_instruction_symbols_are_unique_in_word_order():
    assert instruction_symbols_for_word("mummy", frozenset({"M", "U"})) == ("M", "U")


def test_audio_without_instruction_symbols_matches_plain_word_synthesis():
    params = AudioParameters(character_speed_wpm=25, effective_speed_wpm=25)
    words = ["ar"]

    samples, timeline = build_word_detection_audio(words, ("A", "R"), params)

    np.testing.assert_array_equal(samples, synth.synthesize_words(words, params))
    assert timeline == synth.compute_word_timeline(words, params)


def test_audio_inserts_spoken_instruction_before_focus_word():
    params = AudioParameters(character_speed_wpm=25, effective_speed_wpm=25)
    plain_samples = synth.synthesize_words(["km"], params)
    prompted_samples, prompted_timeline = build_word_detection_audio(["km"], ("K",), params)

    assert len(prompted_samples) > len(plain_samples)
    assert prompted_timeline[0][0] == "K"
    assert prompted_timeline[0][1] > 0.0


def test_multi_symbol_prompt_includes_and_wav(monkeypatch, tmp_path):
    params = AudioParameters(character_speed_wpm=25, effective_speed_wpm=25)
    anchors_dir = tmp_path / "nato_phonetic"
    instruction_dir = tmp_path / "instruction"
    loaded_names: list[str] = []

    samples_by_name = {
        "listen-for.wav": np.array([0.1], dtype=np.float32),
        "kilo.wav": np.array([0.2], dtype=np.float32),
        "and.wav": np.array([0.3], dtype=np.float32),
        "mike.wav": np.array([0.4], dtype=np.float32),
    }

    def fake_load_wav(path):
        loaded_names.append(path.name)
        return samples_by_name[path.name], params.sample_rate_hz

    monkeypatch.setattr(word_detection_audio, "find_anchors_dir", lambda: anchors_dir)
    monkeypatch.setattr(word_detection_audio, "find_instruction_dir", lambda: instruction_dir)
    monkeypatch.setattr(word_detection_audio, "load_wav", fake_load_wav)

    samples, timeline = build_word_detection_audio(["km"], ("K", "M"), params)

    assert loaded_names == ["listen-for.wav", "kilo.wav", "and.wav", "mike.wav"]
    np.testing.assert_array_equal(samples[:4], np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32))
    assert timeline[0][1] == 4 / params.sample_rate_hz


def test_prompt_wavs_are_resampled_to_session_rate(monkeypatch, tmp_path):
    params = AudioParameters(character_speed_wpm=25, effective_speed_wpm=25)
    anchors_dir = tmp_path / "nato_phonetic"
    instruction_dir = tmp_path / "instruction"

    def fake_load_wav(path):
        return np.array([0.0, 1.0], dtype=np.float32), params.sample_rate_hz // 2

    monkeypatch.setattr(word_detection_audio, "find_anchors_dir", lambda: anchors_dir)
    monkeypatch.setattr(word_detection_audio, "find_instruction_dir", lambda: instruction_dir)
    monkeypatch.setattr(word_detection_audio, "load_wav", fake_load_wav)

    samples, timeline = build_word_detection_audio(["k"], ("K",), params)

    assert timeline[0][1] == 8 / params.sample_rate_hz
    np.testing.assert_array_equal(samples[:4], np.array([0.0, 0.5, 1.0, 1.0], dtype=np.float32))


def test_prompted_audio_preserves_internal_morse_spacing():
    params = AudioParameters(character_speed_wpm=20, effective_speed_wpm=10)
    _, timeline = build_word_detection_audio(["km"], ("K", "M"), params)

    gap = timeline[1][1] - timeline[0][2]
    assert math.isclose(
        gap, timing.inter_character_seconds(params), abs_tol=1 / params.sample_rate_hz
    )
