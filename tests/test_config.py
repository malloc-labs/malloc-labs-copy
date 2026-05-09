"""Tests for copy_653.config."""

import textwrap
import tomllib
from pathlib import Path

import pytest

from copy_653.audio.parameters import AudioParameters
from copy_653.config import load_audio_parameters


def test_returns_defaults_when_file_missing(tmp_path: Path):
    # First-run state: no config file exists yet. This is normal, not
    # an error — fall back to defaults silently.
    nonexistent = tmp_path / "no_config.toml"
    assert load_audio_parameters(nonexistent) == AudioParameters()


def test_reads_audio_table_overrides(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
            [audio]
            character_speed_wpm = 25
            tone_frequency_hz = 700
            amplitude = 0.5
            """))
    params = load_audio_parameters(config_file)
    assert params.character_speed_wpm == 25
    assert params.tone_frequency_hz == 700
    assert params.amplitude == 0.5
    # Unmentioned fields take their defaults.
    assert params.effective_speed_wpm == 10
    assert params.sample_rate_hz == 48_000


def test_accepts_string_output_device(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[audio]\noutput_device = "Mac mini Speakers"\n')
    params = load_audio_parameters(config_file)
    assert params.output_device == "Mac mini Speakers"


def test_accepts_int_output_device(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[audio]\noutput_device = 3\n")
    params = load_audio_parameters(config_file)
    assert params.output_device == 3


def test_propagates_validation_error_for_invalid_value(tmp_path: Path):
    # Negative WPM is rejected by AudioParameters. The loader must not
    # swallow the error and silently substitute defaults — that would
    # violate the honesty contract (spec §1.5).
    config_file = tmp_path / "config.toml"
    config_file.write_text("[audio]\ncharacter_speed_wpm = -5\n")
    with pytest.raises(ValueError):
        load_audio_parameters(config_file)


def test_propagates_amplitude_out_of_range(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[audio]\namplitude = 2.0\n")
    with pytest.raises(ValueError):
        load_audio_parameters(config_file)


def test_propagates_toml_parse_error(tmp_path: Path):
    # Malformed TOML surfaces honestly; we do not pretend the file
    # was empty.
    config_file = tmp_path / "config.toml"
    config_file.write_text("not valid toml [[[[")
    with pytest.raises(tomllib.TOMLDecodeError):
        load_audio_parameters(config_file)


def test_unknown_audio_keys_are_silently_ignored(tmp_path: Path):
    # Forward compatibility: a config written for a newer Copy with
    # extra keys should not break older installs.
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
            [audio]
            character_speed_wpm = 22
            mystery_field = "from a future copy_653"
            """))
    params = load_audio_parameters(config_file)
    assert params.character_speed_wpm == 22


def test_unknown_top_level_tables_are_silently_ignored(tmp_path: Path):
    # [midi] and friends are not yet implemented; their presence in
    # the config must not break audio loading.
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
            [audio]
            character_speed_wpm = 22

            [midi]
            device = "Trinkey"
            """))
    params = load_audio_parameters(config_file)
    assert params.character_speed_wpm == 22


def test_returns_defaults_when_audio_table_missing(tmp_path: Path):
    # File exists but has no [audio] section — defaults all the way.
    config_file = tmp_path / "config.toml"
    config_file.write_text('[paths]\nsessions = "~/sessions"\n')
    params = load_audio_parameters(config_file)
    assert params == AudioParameters()
