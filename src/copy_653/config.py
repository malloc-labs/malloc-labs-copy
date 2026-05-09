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

import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Iterable

import tomli_w

from copy_653.audio import patterns
from copy_653.audio.parameters import AudioParameters

# XDG-style default. Used on both Linux and macOS for consistency
# (rather than ~/Library/Application Support on macOS) — see spec §6.3.
DEFAULT_CONFIG_PATH = Path.home() / ".local" / "share" / "copy_653" / "config.toml"

# Dev default for a generated session's audio length. Spec §4.2 says
# Detection is 2 minutes by default; that lives in [session] alongside
# this when session/ proper lands. 30 seconds is a development default
# — long enough to hear randomness, short enough to iterate.
DEFAULT_SESSION_DURATION_SECONDS = 30.0


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

    config_path.parent.mkdir(parents=True, exist_ok=True)
    serialised = tomli_w.dumps(data).encode("utf-8")

    # Write to a temp file in the same directory, then atomic rename.
    # Same-directory placement guarantees the rename does not cross a
    # filesystem boundary (which would silently fall back to copy-then-
    # delete and lose the atomicity).
    fd, tmp_path = tempfile.mkstemp(prefix=".config-", suffix=".toml", dir=config_path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(serialised)
        os.replace(tmp_path, config_path)
    except Exception:
        # Cleanup on failure; the caller sees the original exception.
        Path(tmp_path).unlink(missing_ok=True)
        raise


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
