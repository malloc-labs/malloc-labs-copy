"""Config file loading.

Copy reads its runtime configuration from a TOML file at a known
location. The file is optional — when absent, all parameters take
their defaults from the dataclasses they configure (see
:mod:`copy_653.audio.parameters`).

Per spec §6.1 / §6.3:
- Format: TOML.
- Default location: ``~/.local/share/copy_653/config.toml``
  (XDG-style, used on both Linux and macOS for consistency).
- Override: pass an explicit path to :func:`load_audio_parameters`.

Per spec §1.5, parse and validation failures surface plainly. If the
file exists but cannot be parsed, or holds an invalid value, the
exception propagates rather than silently falling back to defaults.
The honesty contract extends to configuration: what the learner has
written is what is read, and if it is wrong they hear about it
immediately rather than discovering it via mysteriously unchanged
behaviour.

Forward compatibility: unknown keys in the ``[audio]`` table and
unknown top-level tables are silently ignored, so a config file
written for a newer version of Copy does not break an older install.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from copy_653.audio.parameters import AudioParameters

# XDG-style default. Used on both Linux and macOS for consistency
# (rather than ~/Library/Application Support on macOS) — see spec §6.3.
DEFAULT_CONFIG_PATH = Path.home() / ".local" / "share" / "copy_653" / "config.toml"


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
    config_path = path if path is not None else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        return AudioParameters()

    with config_path.open("rb") as f:
        data = tomllib.load(f)

    audio_table: dict[str, Any] = data.get("audio", {})

    # Filter to fields that AudioParameters actually accepts. Anything
    # else in the table is forward-compat noise (or an outright typo
    # the user will discover when their setting "doesn't take" — a
    # known limitation of silent-ignore; see spec §1.5 commentary).
    known_keys = set(AudioParameters.__dataclass_fields__.keys())
    filtered = {k: v for k, v in audio_table.items() if k in known_keys}

    return AudioParameters(**filtered)
