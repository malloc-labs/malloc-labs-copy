"""Config file loading and persistence.

Copy reads its runtime configuration from a TOML file at a known
location. The file is optional — when absent, every value falls back
to its in-code default. The same file holds three concerns today,
each in its own table:

- ``[audio]`` — sample rate, WPM, tone, amplitude (see
  :mod:`copy_653.audio.parameters`). Hand-authored.
- ``[symbols]`` — the learner's claimed symbol set (spec §2.5, §6.1).
  Read by anything that gates the stream, written by the engine when
  the learner claims a new symbol.
- ``[session]`` — runtime knobs for sessions. Currently just the dev
  default ``duration_seconds``; spec §4.2 will eventually add
  per-mode keys.
- ``[midi.key]`` — physical key input defaults for the reference
  TRRS Trinkey and Copy-owned sidetone.

Per spec §6.1 / §6.3:

- Format: TOML.
- Default location: ``~/.local/share/copy_653/config.toml``
  (XDG-style, used on both Linux and macOS for consistency).
- Override: pass an explicit path to any loader.

Per spec §1.5, parse and validation failures surface plainly. If the
file exists but cannot be parsed, or holds an invalid value, the
exception propagates rather than silently falling back to defaults.
The honesty contract extends to configuration: what the learner has
written is what is read, and if it is wrong they hear about it
immediately rather than discovering it via mysteriously unchanged
behaviour.

Forward compatibility: unknown keys inside known tables and unknown
top-level tables are silently ignored, so a config file written for
a newer version of Copy does not break an older install.

When the engine writes the file (e.g. on claim-symbol), the write is
atomic — a temp file in the same directory is filled and ``rename``-d
into place — so a crash mid-write cannot leave a half-written config.
Comments and key ordering in the original file are NOT preserved on
write; ``tomli_w`` is a round-tripper, not a formatter. Hand-authored
comments survive only as long as no programmatic write occurs.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Iterable

import tomli_w

from copy_653.audio import patterns
from copy_653.audio.parameters import AudioParameters
from copy_653.audio.texture import envelope_seconds_for_tone_shape
from copy_653.letters.sequence import LettersConfig

# XDG-style default. Used on both Linux and macOS for consistency
# (rather than ~/Library/Application Support on macOS) — see spec §6.3.
DEFAULT_CONFIG_PATH = Path.home() / ".local" / "share" / "copy_653" / "config.toml"

# Dev default for a generated session's audio length. Spec §4.2 says
# Detection is 2 minutes by default; that lives in [session] alongside
# this when session/ proper lands. 30 seconds is a development default
# — long enough to hear randomness, short enough to iterate.
DEFAULT_SESSION_DURATION_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class KeyerSettings:
    """Settings for physical key input and local sidetone behaviour."""

    trinkey_buzzer_enabled: bool = False
    dit_note: int = 1
    dah_note: int = 2
    straight_note: int = 0
    dit_ms: int = 100
    character_gap_dits: int = 3


# ---------- audio ------------------------------------------------------


def load_audio_parameters(path: Path | None = None) -> AudioParameters:
    """Load audio parameters from the TOML config file.

    If ``path`` is ``None``, use :data:`DEFAULT_CONFIG_PATH`. If the
    file does not exist (at either the explicit or default path),
    return :class:`AudioParameters` with all defaults — a missing
    config file is the normal first-run state, not an error.

    If the file exists, parse it and pass the contents of the
    ``[audio]`` table as keyword arguments to
    :class:`AudioParameters`. Validation runs in
    ``AudioParameters.__post_init__`` and any ``ValueError`` it raises
    propagates unchanged.

    Unknown keys in the ``[audio]`` table are silently ignored
    (forward compatibility). Unknown top-level tables are likewise
    ignored.
    """
    data = _read_toml(path)
    if data is None:
        return AudioParameters()

    audio_table: dict[str, Any] = data.get("audio", {})

    # Filter to fields that AudioParameters actually accepts. Anything
    # else in the table is forward-compat noise (or an outright typo
    # the user will discover when their setting "doesn't take" — a
    # known limitation of silent-ignore; see spec §1.5 commentary).
    known_keys = set(AudioParameters.__dataclass_fields__.keys())
    filtered = {k: v for k, v in audio_table.items() if k in known_keys}

    return AudioParameters(**filtered)


def save_audio_timing(
    *,
    character_speed_wpm: int,
    effective_speed_wpm: int,
    tone_shape: int | None = None,
    receiver_bed: int | None = None,
    cadence_variation: int | None = None,
    path: Path | None = None,
) -> AudioParameters:
    """Persist the learner-facing timing and signal texture settings.

    ``character_speed_wpm`` is how fast the dits and dahs themselves
    are rendered. ``effective_speed_wpm`` is the Farnsworth-managed
    overall pace after spacing is widened.

    Texture values are optional for compatibility with older callers.
    The rest of ``[audio]`` is preserved, so output routing, tone, and
    amplitude settings survive a Settings-page save.
    """
    config_path = path if path is not None else DEFAULT_CONFIG_PATH
    data = _read_toml(config_path) or {}
    audio_table = data.setdefault("audio", {})

    known_keys = set(AudioParameters.__dataclass_fields__.keys())
    filtered = {k: v for k, v in audio_table.items() if k in known_keys}
    filtered["character_speed_wpm"] = character_speed_wpm
    filtered["effective_speed_wpm"] = effective_speed_wpm
    if tone_shape is not None:
        filtered["envelope_ramp_seconds"] = envelope_seconds_for_tone_shape(tone_shape)
    if receiver_bed is not None:
        filtered["receiver_bed"] = receiver_bed
    if cadence_variation is not None:
        filtered["cadence_variation"] = cadence_variation
    params = AudioParameters(**filtered)

    audio_table["character_speed_wpm"] = params.character_speed_wpm
    audio_table["effective_speed_wpm"] = params.effective_speed_wpm
    if tone_shape is not None:
        audio_table["envelope_ramp_seconds"] = params.envelope_ramp_seconds
    if receiver_bed is not None:
        audio_table["receiver_bed"] = params.receiver_bed
    if cadence_variation is not None:
        audio_table["cadence_variation"] = params.cadence_variation
    _write_toml_atomic(data, config_path)
    return params


# ---------- key input ---------------------------------------------------


def load_keyer_settings(path: Path | None = None) -> KeyerSettings:
    """Load physical key input settings from ``[midi.key]``.

    Missing settings default to Copy owning the sidetone, with the
    Trinkey buzzer disabled.
    """
    data = _read_toml(path)
    if data is None:
        return KeyerSettings()

    midi_table = data.get("midi", {})
    if not isinstance(midi_table, dict):
        return KeyerSettings()
    key_table = midi_table.get("key", {})
    if not isinstance(key_table, dict):
        return KeyerSettings()

    return KeyerSettings(
        trinkey_buzzer_enabled=_key_bool(
            key_table.get("trinkey_buzzer_enabled"),
            "trinkey_buzzer_enabled",
            default=False,
        ),
        dit_note=_key_midi_note(key_table.get("dit_note"), "dit_note", default=1),
        dah_note=_key_midi_note(key_table.get("dah_note"), "dah_note", default=2),
        straight_note=_key_midi_note(key_table.get("straight_note"), "straight_note", default=0),
        dit_ms=_key_positive_int(key_table.get("dit_ms"), "dit_ms", default=100),
        character_gap_dits=_key_positive_int(
            key_table.get("character_gap_dits"),
            "character_gap_dits",
            default=3,
        ),
    )


def _key_bool(value: Any, field: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"[midi.key].{field} must be a boolean, got {type(value).__name__}")
    return value


def _key_positive_int(value: Any, field: str, *, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"[midi.key].{field} must be a positive integer")
    if value <= 0:
        raise ValueError(f"[midi.key].{field} must be a positive integer")
    return value


def _key_midi_note(value: Any, field: str, *, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"[midi.key].{field} must be a MIDI note from 0 to 127")
    if not 0 <= value <= 127:
        raise ValueError(f"[midi.key].{field} must be a MIDI note from 0 to 127")
    return value


def save_keyer_settings(
    *,
    trinkey_buzzer_enabled: bool,
    dit_note: int | None = None,
    dah_note: int | None = None,
    straight_note: int | None = None,
    dit_ms: int | None = None,
    character_gap_dits: int | None = None,
    path: Path | None = None,
) -> KeyerSettings:
    """Persist physical key input settings, preserving other tables."""
    config_path = path if path is not None else DEFAULT_CONFIG_PATH
    data = _read_toml(config_path) or {}
    current = load_keyer_settings(config_path)

    midi_table = data.get("midi")
    if not isinstance(midi_table, dict):
        midi_table = {}
        data["midi"] = midi_table
    key_table = midi_table.get("key")
    if not isinstance(key_table, dict):
        key_table = {}
        midi_table["key"] = key_table

    settings = KeyerSettings(
        trinkey_buzzer_enabled=_key_bool(
            trinkey_buzzer_enabled,
            "trinkey_buzzer_enabled",
            default=current.trinkey_buzzer_enabled,
        ),
        dit_note=_key_midi_note(dit_note, "dit_note", default=current.dit_note),
        dah_note=_key_midi_note(dah_note, "dah_note", default=current.dah_note),
        straight_note=_key_midi_note(
            straight_note,
            "straight_note",
            default=current.straight_note,
        ),
        dit_ms=_key_positive_int(dit_ms, "dit_ms", default=current.dit_ms),
        character_gap_dits=_key_positive_int(
            character_gap_dits,
            "character_gap_dits",
            default=current.character_gap_dits,
        ),
    )

    key_table["trinkey_buzzer_enabled"] = settings.trinkey_buzzer_enabled
    key_table["dit_note"] = settings.dit_note
    key_table["dah_note"] = settings.dah_note
    key_table["straight_note"] = settings.straight_note
    key_table["dit_ms"] = settings.dit_ms
    key_table["character_gap_dits"] = settings.character_gap_dits

    _write_toml_atomic(data, config_path)
    return settings


# ---------- claimed symbols --------------------------------------------


def load_claimed_symbols(path: Path | None = None) -> tuple[str, ...]:
    """Load the learner's claimed symbol set.

    Reads ``[symbols].claimed`` from the config TOML. If the file does
    not exist, or the table is missing, returns
    :data:`copy_653.audio.patterns.KOCH_FIRST_PAIR` — the spec §2.5
    starting set.

    Validation (spec §1.5):

    - Must be a list of strings.
    - Each entry must be a known pattern (raises ``ValueError`` with
      the offending symbol if not).
    - Duplicates raise ``ValueError`` — a claimed set is, by name, a
      set.
    """
    data = _read_toml(path)
    if data is None:
        return patterns.KOCH_FIRST_PAIR

    symbols_table: dict[str, Any] = data.get("symbols", {})
    claimed = symbols_table.get("claimed")
    if claimed is None:
        return patterns.KOCH_FIRST_PAIR

    if not isinstance(claimed, list):
        raise ValueError(f"[symbols].claimed must be a list, got {type(claimed).__name__}")
    if not all(isinstance(s, str) for s in claimed):
        raise ValueError("[symbols].claimed must contain only strings")
    upper = [s.upper() for s in claimed]
    if len(set(upper)) != len(upper):
        raise ValueError(f"[symbols].claimed contains duplicates: {claimed!r}")
    for symbol in upper:
        try:
            patterns.pattern_for(symbol)
        except KeyError as exc:
            raise ValueError(f"[symbols].claimed contains unknown symbol {exc.args[0]!r}") from exc

    return tuple(upper)


def save_claimed_symbols(symbols: Iterable[str], path: Path | None = None) -> None:
    """Persist the claimed symbol set, preserving every other table.

    Reads the existing config (if any), replaces ``[symbols].claimed``,
    and writes the file atomically. ``[audio]`` and any other tables
    survive unchanged in their data, but per the module docstring
    comments are not preserved.

    Writes through a temp file in the same directory followed by
    :func:`os.replace`, so a crash mid-write cannot truncate the
    config. Creates parent directories on first use.

    Validation matches :func:`load_claimed_symbols` so a hand-mistake
    is caught at write time rather than reappearing as a load error.
    """
    config_path = path if path is not None else DEFAULT_CONFIG_PATH

    upper = [s.upper() for s in symbols]
    if len(set(upper)) != len(upper):
        raise ValueError(f"symbols contains duplicates: {list(symbols)!r}")
    for symbol in upper:
        try:
            patterns.pattern_for(symbol)
        except KeyError as exc:
            raise ValueError(f"symbols contains unknown symbol {exc.args[0]!r}") from exc

    data = _read_toml(config_path) or {}
    data.setdefault("symbols", {})["claimed"] = upper

    _write_toml_atomic(data, config_path)


# ---------- session ----------------------------------------------------


def load_session_duration(path: Path | None = None) -> float:
    """Load the dev session duration in seconds.

    Reads ``[session].duration_seconds`` from the config TOML. Defaults
    to :data:`DEFAULT_SESSION_DURATION_SECONDS` (30.0) if missing.

    Validation: must be a positive number. Raises ``ValueError``
    otherwise.
    """
    data = _read_toml(path)
    if data is None:
        return DEFAULT_SESSION_DURATION_SECONDS

    session_table: dict[str, Any] = data.get("session", {})
    raw = session_table.get("duration_seconds")
    if raw is None:
        return DEFAULT_SESSION_DURATION_SECONDS

    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise ValueError(f"[session].duration_seconds must be a number, got {type(raw).__name__}")
    value = float(raw)
    if value <= 0:
        raise ValueError(f"[session].duration_seconds must be positive, got {value}")
    return value


# ---------- letters ----------------------------------------------------


def load_letters_config(path: Path | None = None) -> LettersConfig:
    """Load the letter listening sequence pacing knobs.

    Reads the ``[letters]`` table from the config TOML. If the file
    or table is missing, returns :class:`LettersConfig` with all
    defaults — first-run users get a sensible sequence without
    touching configuration.

    Validation runs in :class:`LettersConfig.__post_init__` and any
    ``ValueError`` it raises propagates unchanged (spec §1.5).

    Unknown keys in the ``[letters]`` table are silently ignored
    (forward compatibility).
    """
    data = _read_toml(path)
    if data is None:
        return LettersConfig()

    letters_table: dict[str, Any] = data.get("letters", {})

    known_keys = set(LettersConfig.__dataclass_fields__.keys())
    filtered = {k: v for k, v in letters_table.items() if k in known_keys}

    return LettersConfig(**filtered)


# ---------- internal ---------------------------------------------------


def _read_toml(path: Path | None) -> dict[str, Any] | None:
    """Read the config TOML; return parsed dict, or ``None`` if missing.

    Errors during parse propagate per spec §1.5.
    """
    config_path = path if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return None
    with config_path.open("rb") as f:
        return tomllib.load(f)


def _write_toml_atomic(data: dict[str, Any], config_path: Path) -> None:
    """Write TOML to ``config_path`` through a same-directory temp file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    serialised = tomli_w.dumps(data).encode("utf-8")

    # Same-directory placement guarantees os.replace remains atomic
    # rather than crossing filesystems and degrading to copy/delete.
    fd, tmp_path = tempfile.mkstemp(prefix=".config-", suffix=".toml", dir=config_path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(serialised)
        os.replace(tmp_path, config_path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
