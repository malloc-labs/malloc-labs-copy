"""Tests for copy_653.config."""

import textwrap
import tomllib
from pathlib import Path

import pytest

from copy_653.audio import patterns
from copy_653.audio.parameters import AudioParameters
from copy_653.config import (
    DEFAULT_SESSION_DURATION_SECONDS,
    load_audio_parameters,
    load_claimed_symbols,
    load_session_duration,
    save_claimed_symbols,
)


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


# ---------- claimed symbols --------------------------------------------


def test_load_claimed_symbols_returns_koch_first_pair_when_file_missing(tmp_path: Path):
    nonexistent = tmp_path / "no_config.toml"
    assert load_claimed_symbols(nonexistent) == patterns.KOCH_FIRST_PAIR


def test_load_claimed_symbols_returns_koch_first_pair_when_table_missing(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[audio]\ncharacter_speed_wpm = 22\n")
    assert load_claimed_symbols(config_file) == patterns.KOCH_FIRST_PAIR


def test_load_claimed_symbols_reads_table(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
        [symbols]
        claimed = ["K", "M", "U"]
        """))
    assert load_claimed_symbols(config_file) == ("K", "M", "U")


def test_load_claimed_symbols_uppercases(tmp_path: Path):
    # Hand-edits with lowercase letters should still load.
    config_file = tmp_path / "config.toml"
    config_file.write_text('[symbols]\nclaimed = ["k", "m"]\n')
    assert load_claimed_symbols(config_file) == ("K", "M")


def test_load_claimed_symbols_rejects_unknown(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[symbols]\nclaimed = ["K", "!"]\n')
    with pytest.raises(ValueError, match="unknown symbol"):
        load_claimed_symbols(config_file)


def test_load_claimed_symbols_rejects_duplicates(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[symbols]\nclaimed = ["K", "K", "M"]\n')
    with pytest.raises(ValueError, match="duplicates"):
        load_claimed_symbols(config_file)


def test_load_claimed_symbols_rejects_non_list(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[symbols]\nclaimed = "KM"\n')
    with pytest.raises(ValueError, match="must be a list"):
        load_claimed_symbols(config_file)


def test_save_claimed_symbols_writes_new_file(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    save_claimed_symbols(("K", "M", "U"), config_file)
    assert load_claimed_symbols(config_file) == ("K", "M", "U")


def test_save_claimed_symbols_creates_parent_dirs(tmp_path: Path):
    nested = tmp_path / "deep" / "deeper" / "config.toml"
    save_claimed_symbols(("K", "M"), nested)
    assert nested.exists()
    assert load_claimed_symbols(nested) == ("K", "M")


def test_save_claimed_symbols_preserves_audio_table(tmp_path: Path):
    # Round-trip: a learner's hand-edited [audio] settings must
    # survive a programmatic claim. Comments would not (documented).
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
        [audio]
        character_speed_wpm = 22
        tone_frequency_hz = 700
        """))
    save_claimed_symbols(("K", "M", "U"), config_file)

    audio = load_audio_parameters(config_file)
    assert audio.character_speed_wpm == 22
    assert audio.tone_frequency_hz == 700
    assert load_claimed_symbols(config_file) == ("K", "M", "U")


def test_save_claimed_symbols_overwrites_existing_claim(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    save_claimed_symbols(("K", "M"), config_file)
    save_claimed_symbols(("K", "M", "U"), config_file)
    assert load_claimed_symbols(config_file) == ("K", "M", "U")


def test_save_claimed_symbols_rejects_unknown(tmp_path: Path):
    with pytest.raises(ValueError, match="unknown symbol"):
        save_claimed_symbols(("K", "!"), tmp_path / "config.toml")


def test_save_claimed_symbols_rejects_duplicates(tmp_path: Path):
    with pytest.raises(ValueError, match="duplicates"):
        save_claimed_symbols(("K", "K"), tmp_path / "config.toml")


# ---------- session duration -------------------------------------------


def test_load_session_duration_default_when_file_missing(tmp_path: Path):
    nonexistent = tmp_path / "no_config.toml"
    assert load_session_duration(nonexistent) == DEFAULT_SESSION_DURATION_SECONDS


def test_load_session_duration_default_when_table_missing(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[audio]\ncharacter_speed_wpm = 22\n")
    assert load_session_duration(config_file) == DEFAULT_SESSION_DURATION_SECONDS


def test_load_session_duration_reads_value(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[session]\nduration_seconds = 60\n")
    assert load_session_duration(config_file) == 60.0


def test_load_session_duration_accepts_float(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[session]\nduration_seconds = 12.5\n")
    assert load_session_duration(config_file) == 12.5


def test_load_session_duration_rejects_non_positive(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[session]\nduration_seconds = 0\n")
    with pytest.raises(ValueError, match="positive"):
        load_session_duration(config_file)


def test_load_session_duration_rejects_non_number(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[session]\nduration_seconds = "thirty"\n')
    with pytest.raises(ValueError, match="must be a number"):
        load_session_duration(config_file)
