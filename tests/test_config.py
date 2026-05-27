"""Tests for copy_653.config."""

import textwrap
import tomllib
from pathlib import Path

import pytest

from copy_653.audio import patterns
from copy_653.audio.parameters import AudioParameters
from copy_653.config import (
    DEFAULT_SESSION_DURATION_SECONDS,
    KeyerSettings,
    RecognitionSettings,
    ServerSettings,
    load_audio_parameters,
    load_claimed_symbols,
    load_keyer_settings,
    load_letters_config,
    load_recognition_settings,
    load_save_directory,
    load_server_settings,
    load_session_duration,
    save_audio_timing,
    save_claimed_symbols,
    save_keyer_settings,
    save_recognition_settings,
    save_save_directory,
)
from copy_653.letters.sequence import LettersConfig

# ---------- server -----------------------------------------------------


def test_load_server_settings_defaults_when_file_missing(tmp_path: Path):
    assert load_server_settings(tmp_path / "missing.toml") == ServerSettings()


def test_load_server_settings_reads_server_table(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
            [server]
            host = "127.0.0.1"
            port = 8653
            port_search_span = 1
            """))

    assert load_server_settings(config_file) == ServerSettings(
        host="127.0.0.1",
        port=8653,
        port_search_span=1,
    )


@pytest.mark.parametrize(
    ("toml", "field"),
    [
        ('host = ""', "host"),
        ("host = 123", "host"),
        ("port = 0", "port"),
        ("port = 65536", "port"),
        ('port = "8653"', "port"),
        ("port_search_span = 0", "port_search_span"),
    ],
)
def test_load_server_settings_rejects_invalid_values(
    tmp_path: Path,
    toml: str,
    field: str,
):
    config_file = tmp_path / "config.toml"
    config_file.write_text(f"[server]\n{toml}\n")

    with pytest.raises(ValueError, match=field):
        load_server_settings(config_file)


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
            receiver_bed = 2
            cadence_variation = 1
            """))
    params = load_audio_parameters(config_file)
    assert params.character_speed_wpm == 25
    assert params.tone_frequency_hz == 700
    assert params.amplitude == 0.5
    assert params.receiver_bed == 2
    assert params.cadence_variation == 1
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


def test_save_audio_timing_writes_new_file(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    params = save_audio_timing(
        character_speed_wpm=22,
        effective_speed_wpm=12,
        tone_shape=3,
        receiver_bed=2,
        cadence_variation=1,
        path=config_file,
    )

    assert params.character_speed_wpm == 22
    assert params.effective_speed_wpm == 12
    assert params.envelope_ramp_seconds == 0.007
    assert params.receiver_bed == 2
    assert params.cadence_variation == 1
    loaded = load_audio_parameters(config_file)
    assert loaded.character_speed_wpm == 22
    assert loaded.effective_speed_wpm == 12
    assert loaded.envelope_ramp_seconds == 0.007
    assert loaded.receiver_bed == 2
    assert loaded.cadence_variation == 1


def test_save_audio_timing_preserves_other_audio_and_tables(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
        [audio]
        character_speed_wpm = 20
        effective_speed_wpm = 10
        tone_frequency_hz = 700
        amplitude = 0.4
        receiver_bed = 4
        cadence_variation = 2
        output_device = "Mac mini Speakers"

        [symbols]
        claimed = ["K", "M"]
        """))

    save_audio_timing(character_speed_wpm=25, effective_speed_wpm=15, path=config_file)

    loaded = load_audio_parameters(config_file)
    assert loaded.character_speed_wpm == 25
    assert loaded.effective_speed_wpm == 15
    assert loaded.tone_frequency_hz == 700
    assert loaded.amplitude == 0.4
    assert loaded.receiver_bed == 4
    assert loaded.cadence_variation == 2
    assert loaded.output_device == "Mac mini Speakers"
    assert load_claimed_symbols(config_file) == ("K", "M")


def test_save_audio_timing_can_replace_invalid_existing_timing(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
        [audio]
        character_speed_wpm = 10
        effective_speed_wpm = 20
        tone_frequency_hz = 700
        """))

    save_audio_timing(character_speed_wpm=20, effective_speed_wpm=10, path=config_file)

    loaded = load_audio_parameters(config_file)
    assert loaded.character_speed_wpm == 20
    assert loaded.effective_speed_wpm == 10
    assert loaded.tone_frequency_hz == 700


def test_save_audio_timing_rejects_farnsworth_faster_than_koch(tmp_path: Path):
    with pytest.raises(ValueError, match="cannot exceed"):
        save_audio_timing(character_speed_wpm=10, effective_speed_wpm=20, path=tmp_path / "c.toml")


def test_save_audio_timing_rejects_non_positive_wpm(tmp_path: Path):
    with pytest.raises(ValueError, match="positive"):
        save_audio_timing(character_speed_wpm=0, effective_speed_wpm=10, path=tmp_path / "c.toml")


def test_save_audio_timing_rejects_invalid_texture_values(tmp_path: Path):
    with pytest.raises(ValueError, match="tone_shape"):
        save_audio_timing(
            character_speed_wpm=20,
            effective_speed_wpm=10,
            tone_shape=11,
            path=tmp_path / "c.toml",
        )
    with pytest.raises(ValueError, match="receiver_bed"):
        save_audio_timing(
            character_speed_wpm=20,
            effective_speed_wpm=10,
            receiver_bed=-1,
            path=tmp_path / "c.toml",
        )
    with pytest.raises(ValueError, match="cadence_variation"):
        save_audio_timing(
            character_speed_wpm=20,
            effective_speed_wpm=10,
            cadence_variation=6,
            path=tmp_path / "c.toml",
        )


# ---------- key input ---------------------------------------------------


def test_load_keyer_settings_returns_defaults_when_table_missing(tmp_path: Path):
    assert load_keyer_settings(tmp_path / "missing.toml") == KeyerSettings(
        input_name="TRRS Trinkey",
        dit_note=1,
        dah_note=2,
        straight_note=0,
    )


def test_load_keyer_settings_reads_key_table(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
        [midi.key]
        input_name = "TRRS Trinkey M0"
        dit_note = 1
        dah_note = 2
        straight_note = 0
        """))

    assert load_keyer_settings(config_file) == KeyerSettings(
        input_name="TRRS Trinkey M0",
        dit_note=1,
        dah_note=2,
        straight_note=0,
    )


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ("input_name = false", "input_name"),
        ("dit_note = -1", "dit_note"),
        ("dah_note = 128", "dah_note"),
        ("straight_note = true", "straight_note"),
    ],
)
def test_load_keyer_settings_rejects_invalid_values(
    tmp_path: Path,
    toml: str,
    message: str,
):
    config_file = tmp_path / "config.toml"
    config_file.write_text(f"[midi.key]\n{toml}\n")

    with pytest.raises(ValueError, match=message):
        load_keyer_settings(config_file)


def test_save_keyer_settings_preserves_other_tables(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
        [audio]
        character_speed_wpm = 22

        [symbols]
        claimed = ["K", "M"]
        """))

    saved = save_keyer_settings(
        input_name="TRRS Trinkey M0",
        path=config_file,
    )

    assert saved == KeyerSettings(
        input_name="TRRS Trinkey M0",
    )
    assert load_keyer_settings(config_file) == KeyerSettings(
        input_name="TRRS Trinkey M0",
    )
    assert load_audio_parameters(config_file).character_speed_wpm == 22
    assert load_claimed_symbols(config_file) == ("K", "M")


def test_load_keyer_settings_defaults_keyer_mode_to_iambic_a(tmp_path: Path):
    assert load_keyer_settings(tmp_path / "missing.toml").keyer_mode == "iambic_a"


def test_load_keyer_settings_reads_keyer_mode(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
        [midi.key]
        keyer_mode = "ultimatic"
        """))

    assert load_keyer_settings(config_file).keyer_mode == "ultimatic"


def test_load_keyer_settings_rejects_unknown_keyer_mode(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[midi.key]\nkeyer_mode = "iambic_b"\n')

    with pytest.raises(ValueError, match="keyer_mode"):
        load_keyer_settings(config_file)


def test_save_keyer_settings_persists_keyer_mode(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    saved = save_keyer_settings(
        keyer_mode="ultimatic",
        path=config_file,
    )

    assert saved.keyer_mode == "ultimatic"
    assert load_keyer_settings(config_file).keyer_mode == "ultimatic"


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


# ---------- save directory --------------------------------------------


def test_load_save_directory_defaults_to_config_parent_when_file_missing(tmp_path: Path):
    nonexistent = tmp_path / "no_config.toml"
    assert load_save_directory(nonexistent) == tmp_path


def test_load_save_directory_defaults_to_config_parent_when_table_missing(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[audio]\ncharacter_speed_wpm = 22\n")
    assert load_save_directory(config_file) == tmp_path


def test_load_save_directory_reads_value(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    target = tmp_path / "records"
    config_file.write_text(f'[storage]\nsave_directory = "{target}"\n')
    assert load_save_directory(config_file) == target


def test_load_save_directory_expands_tilde(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[storage]\nsave_directory = "~/copy-records"\n')
    expected = Path("~/copy-records").expanduser()
    assert load_save_directory(config_file) == expected


def test_load_save_directory_rejects_empty(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[storage]\nsave_directory = ""\n')
    with pytest.raises(ValueError, match="must not be empty"):
        load_save_directory(config_file)


def test_load_save_directory_rejects_non_string(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[storage]\nsave_directory = 42\n")
    with pytest.raises(ValueError, match="must be a string"):
        load_save_directory(config_file)


def test_save_save_directory_round_trips(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    target = tmp_path / "records"
    save_save_directory(target, path=config_file)
    assert load_save_directory(config_file) == target


def test_save_save_directory_preserves_other_tables(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
            [audio]
            character_speed_wpm = 22
            effective_speed_wpm = 12

            [symbols]
            claimed = ["K", "M"]
            """))

    save_save_directory(tmp_path / "records", path=config_file)

    parsed = tomllib.loads(config_file.read_text())
    assert parsed["audio"]["character_speed_wpm"] == 22
    assert parsed["audio"]["effective_speed_wpm"] == 12
    assert parsed["symbols"]["claimed"] == ["K", "M"]
    assert parsed["storage"]["save_directory"] == str(tmp_path / "records")


def test_save_save_directory_rejects_empty(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    with pytest.raises(ValueError, match="must not be empty"):
        save_save_directory("   ", path=config_file)


# ---------- letters ----------------------------------------------------


def test_load_letters_config_returns_defaults_when_file_missing(tmp_path: Path):
    assert load_letters_config(tmp_path / "no_config.toml") == LettersConfig()


def test_load_letters_config_reads_table_overrides(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
            [letters]
            phonetic_pairs = 2
            bare_repeats = 1
            gap_within_pair_seconds = 0.4
            gap_between_pairs_seconds = 0.7
            gap_between_bare_seconds = 0.5
            """))
    cfg = load_letters_config(config_file)
    assert cfg.phonetic_pairs == 2
    assert cfg.bare_repeats == 1
    assert cfg.gap_within_pair_seconds == 0.4
    assert cfg.gap_between_pairs_seconds == 0.7
    assert cfg.gap_between_bare_seconds == 0.5


def test_load_letters_config_ignores_unknown_keys(tmp_path: Path):
    """Forward-compat: unknown keys do not error, just get dropped."""
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
            [letters]
            phonetic_pairs = 1
            future_knob = "ignored"
            """))
    cfg = load_letters_config(config_file)
    assert cfg.phonetic_pairs == 1
    assert cfg.bare_repeats == LettersConfig().bare_repeats


def test_load_letters_config_propagates_validation_errors(tmp_path: Path):
    """A negative gap raises through __post_init__ (spec §1.5)."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("[letters]\ngap_within_pair_seconds = -1.0\n")
    with pytest.raises(ValueError, match="gap_within_pair_seconds"):
        load_letters_config(config_file)


# ---------- recognition ------------------------------------------------


def test_load_recognition_settings_defaults_when_missing(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    result = load_recognition_settings(config_file)
    assert result == RecognitionSettings()
    assert result.say_before is True
    assert result.morse_count == 1
    assert result.recognition_time_ms == 3000
    assert result.say_after is True


def test_load_recognition_settings_reads_table(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
            [recognition]
            say_before = false
            morse_count = 2
            recognition_time_ms = 5000
            say_after = false
            """))
    cfg = load_recognition_settings(config_file)
    assert cfg.say_before is False
    assert cfg.morse_count == 2
    assert cfg.recognition_time_ms == 5000
    assert cfg.say_after is False


def test_load_recognition_settings_ignores_unknown_keys(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
            [recognition]
            morse_count = 3
            future_knob = "ignored"
            """))
    cfg = load_recognition_settings(config_file)
    assert cfg.morse_count == 3
    assert cfg.say_before is True


def test_recognition_settings_rejects_zero_morse_count():
    with pytest.raises(ValueError, match="morse_count"):
        RecognitionSettings(morse_count=0)


def test_recognition_settings_rejects_negative_recognition_time():
    with pytest.raises(ValueError, match="recognition_time_ms"):
        RecognitionSettings(recognition_time_ms=-1)


def test_recognition_settings_rejects_non_bool_say_before():
    with pytest.raises(ValueError, match="say_before"):
        RecognitionSettings(say_before="yes")


def test_save_recognition_settings_round_trips(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    saved = save_recognition_settings(
        say_before=False,
        morse_count=2,
        recognition_time_ms=5000,
        say_after=False,
        path=config_file,
    )
    loaded = load_recognition_settings(config_file)
    assert loaded == saved
    assert loaded.say_before is False
    assert loaded.morse_count == 2
    assert loaded.recognition_time_ms == 5000
    assert loaded.say_after is False


def test_save_recognition_settings_preserves_other_tables(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(textwrap.dedent("""
            [audio]
            character_speed_wpm = 25

            [symbols]
            claimed = ["K", "M", "U"]
            """))
    save_recognition_settings(
        say_before=True,
        morse_count=1,
        recognition_time_ms=3000,
        say_after=True,
        path=config_file,
    )
    import tomllib

    data = tomllib.loads(config_file.read_text())
    assert data["audio"]["character_speed_wpm"] == 25
    assert data["symbols"]["claimed"] == ["K", "M", "U"]
    assert data["recognition"]["say_before"] is True
