"""Session record writing (spec §5.1, §6.1).

One JSON file per session, written to the configured save directory
on natural session-end. Format is documented in
``docs/specification.md`` §5.1 and the schema is versioned via
``schema_version`` so analysis tools can guard against shape drift.

The two record shapes today:

- ``koch-exercise`` — listen-only Koch Method Exercises session. The
  engine owns the truth (the played symbol timeline).
- ``cadence-send`` — Key → Cadence sending session. The learner keys
  exercises; the record carries both the engine-generated targets and
  the decoded sent stream plus raw MIDI press/release events.

Both records share a common envelope (engine version, timestamps,
audio parameter snapshot, claimed set) so analysis tools can treat
them uniformly.

Files live in per-mode subdirectories under the configured save
directory::

    <save_directory>/koch-exercise/koch-exercise-20260515T193045Z.json
    <save_directory>/cadence-send/cadence-send-20260515T193045Z.json

Writes are atomic — a same-directory temp file is filled and renamed
into place — so a crash mid-write cannot leave a half-written record.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from copy_653 import __version__
from copy_653.audio.parameters import AudioParameters

SCHEMA_VERSION = "1.0"


def _audio_snapshot(params: AudioParameters) -> dict[str, Any]:
    return {
        "character_speed_wpm": params.character_speed_wpm,
        "effective_speed_wpm": params.effective_speed_wpm,
        "tone_frequency_hz": params.tone_frequency_hz,
        "amplitude": params.amplitude,
        "envelope_ramp_seconds": params.envelope_ramp_seconds,
        "receiver_bed": params.receiver_bed,
        "cadence_variation": params.cadence_variation,
        "sample_rate_hz": params.sample_rate_hz,
    }


def _format_iso8601_utc(when: datetime) -> str:
    """Millisecond-precision ISO-8601 UTC with a ``Z`` suffix."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    else:
        when = when.astimezone(timezone.utc)
    millis = when.microsecond // 1000
    return when.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def _format_filename_stamp(when: datetime) -> str:
    """Compact UTC stamp for filenames: ``20260515T193045Z``."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    else:
        when = when.astimezone(timezone.utc)
    return when.strftime("%Y%m%dT%H%M%SZ")


@dataclass(slots=True)
class KochExerciseRecord:
    """A completed Koch Exercises listening session."""

    started_at: datetime
    ended_at: datetime
    audio: AudioParameters
    claimed_set: tuple[str, ...]
    duration_seconds: float
    seed: int
    # Each entry: {"symbol": str, "t_on": float, "t_off": float}
    symbols: list[dict[str, Any]] = field(default_factory=list)

    mode: str = "koch-exercise"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "engine_version": __version__,
            "mode": self.mode,
            "started_at": _format_iso8601_utc(self.started_at),
            "ended_at": _format_iso8601_utc(self.ended_at),
            "audio": _audio_snapshot(self.audio),
            "claimed_set": list(self.claimed_set),
            "duration_seconds": self.duration_seconds,
            "seed": self.seed,
            "symbols": list(self.symbols),
        }


@dataclass(slots=True)
class CadenceSendRecord:
    """A completed Cadence (Key → Send) session."""

    started_at: datetime
    ended_at: datetime
    audio: AudioParameters
    claimed_set: tuple[str, ...]
    request: dict[str, Any]
    seed: int
    exercises: list[str]
    # Decoded sent symbols. Each entry:
    # {"symbol", "pattern", "started_at", "ended_at", "leading_gap"}.
    # Mapping a sent symbol back to a target exercise is left to the
    # replay tool — the server cannot do it honestly because a learner
    # can send symbols that diverge from the target.
    sent: list[dict[str, Any]] = field(default_factory=list)
    # Raw key press/release events. Each entry:
    # {"kind", "note", "pressed", "timestamp"}
    key_events: list[dict[str, Any]] = field(default_factory=list)

    mode: str = "cadence-send"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "engine_version": __version__,
            "mode": self.mode,
            "started_at": _format_iso8601_utc(self.started_at),
            "ended_at": _format_iso8601_utc(self.ended_at),
            "audio": _audio_snapshot(self.audio),
            "claimed_set": list(self.claimed_set),
            "request": dict(self.request),
            "seed": self.seed,
            "exercises": list(self.exercises),
            "sent": list(self.sent),
            "key_events": list(self.key_events),
        }


def write_record(
    record: KochExerciseRecord | CadenceSendRecord,
    save_directory: Path,
) -> Path:
    """Write a session record to ``<save_directory>/<mode>/<stamp>.json``.

    Returns the resolved path written. Creates the per-mode
    subdirectory on first use. Collisions at second resolution are
    handled by appending ``-1``, ``-2``, … suffixes so two sessions
    that start in the same second do not overwrite each other.

    The write is atomic (same-directory temp file followed by
    ``os.replace``), so a crash mid-write cannot leave a partial
    record on disk.
    """
    target_dir = save_directory / record.mode
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = _format_filename_stamp(record.started_at)
    base = f"{record.mode}-{stamp}"
    candidate = target_dir / f"{base}.json"
    suffix = 1
    while candidate.exists():
        candidate = target_dir / f"{base}-{suffix}.json"
        suffix += 1

    serialised = json.dumps(record.to_dict(), indent=2).encode("utf-8")

    fd, tmp_path = tempfile.mkstemp(prefix=".record-", suffix=".json", dir=target_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(serialised)
        os.replace(tmp_path, candidate)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    return candidate
