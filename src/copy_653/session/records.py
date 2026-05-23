"""Session record writing (spec §5.1, §6.1).

One JSON file per session, written to the configured save directory
on natural session-end. Format is documented in
``docs/specification.md`` §5.1 and the schema is versioned via
``schema_version`` so analysis tools can guard against shape drift.

The three record shapes today:

- ``koch-exercise`` — listen-only Koch Method Exercises session. The
  engine owns the truth (the played symbol timeline).
- ``cadence-send`` — Key → Cadence sending session. The learner keys
  exercises; the record carries both the engine-generated targets and
  the decoded sent stream plus raw MIDI press/release events.
- ``copy-key`` — Copy → Key session. The engine plays short exercises
  (single words, 1-3 symbols) and the learner head-copies then keys
  back. Carries both the played symbol timeline and the keying stream.

All records share a common envelope (engine version, timestamps,
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
from copy_653.sequence.cadence_analysis import apply_cadence_analysis
from copy_653.sequence.exercise_analysis import apply_answers_to_entries

SCHEMA_VERSION = "2.1"


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
    """A completed Koch Exercises listening session.

    Schema 2.0 stores each played exercise as an object rather than
    keeping truth and answers in parallel arrays. This keeps the burden
    metadata and saved-answer analysis beside the exact exercise they
    describe.
    """

    started_at: datetime
    ended_at: datetime
    audio: AudioParameters
    claimed_set: tuple[str, ...]
    seed: int
    generation: dict[str, Any] = field(default_factory=dict)
    exercises: list[dict[str, Any]] = field(default_factory=list)
    # Each entry: {"symbol", "t_on", "t_off", "exercise_index", "word_index", "word"}
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
            "seed": self.seed,
            "generation": dict(self.generation),
            "exercises": [dict(exercise) for exercise in self.exercises],
            "symbols": list(self.symbols),
        }


@dataclass(slots=True)
class CadenceSendRecord:
    """A completed Cadence (Key → Send) session."""

    started_at: datetime
    ended_at: datetime
    audio: AudioParameters
    claimed_set: tuple[str, ...]
    seed: int
    generation: dict[str, Any] = field(default_factory=dict)
    exercises: list[dict[str, Any]] = field(default_factory=list)
    request: dict[str, Any] = field(default_factory=dict)
    # Decoded sent symbols. Each entry:
    # {"symbol", "pattern", "started_at", "ended_at", "leading_gap"}.
    # The finalized exercise entries carry derived attempt analysis; the
    # raw sent stream remains here so that analysis stays auditable.
    sent: list[dict[str, Any]] = field(default_factory=list)
    # Raw key press/release events. Each entry:
    # {"kind", "note", "pressed", "timestamp"}
    key_events: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "cadence-send"

    def to_dict(self) -> dict[str, Any]:
        exercises = apply_cadence_analysis(
            [dict(exercise) for exercise in self.exercises],
            sent=list(self.sent),
            key_events=list(self.key_events),
            character_wpm=self.audio.character_speed_wpm,
        )
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "engine_version": __version__,
            "mode": self.mode,
            "started_at": _format_iso8601_utc(self.started_at),
            "ended_at": _format_iso8601_utc(self.ended_at),
            "audio": _audio_snapshot(self.audio),
            "claimed_set": list(self.claimed_set),
            "request": dict(self.request),
            "seed": self.seed,
            "generation": dict(self.generation),
            "exercises": exercises,
            "sent": list(self.sent),
            "key_events": list(self.key_events),
        }
        return payload


@dataclass(slots=True)
class CopyKeyRecord:
    """A completed Copy → Key (head-copy-then-send) session.

    Combines the played audio timeline (like koch-exercise) with the
    keying stream (like cadence-send). Each exercise is a single word
    of 1-3 symbols; the learner hears it, holds it, and keys it back.
    """

    started_at: datetime
    ended_at: datetime
    audio: AudioParameters
    claimed_set: tuple[str, ...]
    seed: int
    generation: dict[str, Any] = field(default_factory=dict)
    exercises: list[dict[str, Any]] = field(default_factory=list)
    # Played symbol timeline. Each entry:
    # {"symbol", "t_on", "t_off", "exercise_index", "word_index", "word"}
    symbols: list[dict[str, Any]] = field(default_factory=list)
    # Decoded sent symbols. Each entry:
    # {"symbol", "pattern", "started_at", "ended_at", "leading_gap"}.
    sent: list[dict[str, Any]] = field(default_factory=list)
    # Raw key press/release events. Each entry:
    # {"kind", "note", "pressed", "timestamp"}
    key_events: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "copy-key"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "engine_version": __version__,
            "mode": self.mode,
            "started_at": _format_iso8601_utc(self.started_at),
            "ended_at": _format_iso8601_utc(self.ended_at),
            "audio": _audio_snapshot(self.audio),
            "claimed_set": list(self.claimed_set),
            "seed": self.seed,
            "generation": dict(self.generation),
            "exercises": [dict(exercise) for exercise in self.exercises],
            "symbols": list(self.symbols),
            "sent": list(self.sent),
            "key_events": list(self.key_events),
        }


def update_koch_answers(path: Path, answers: list[str]) -> int:
    """Rewrite an existing koch-exercise record with learner answers.

    Reads the record at ``path``, sets each exercise object's
    ``answer`` and internal ``analysis`` fields, and writes the result
    back atomically (same-directory temp file followed by
    ``os.replace``). Returns the number of exercises in the record so
    the caller can verify length agreement.

    Raises :class:`ValueError` if the file is not a koch-exercise
    record or if ``answers`` does not match the record's exercise
    count. The caller is responsible for surfacing that error to the
    UI; per the honesty contract (spec §1.5) we do not silently pad or
    truncate.
    """
    data = json.loads(path.read_text())
    if data.get("mode") != "koch-exercise":
        raise ValueError(f"not a koch-exercise record: {path}")
    expected = len(data.get("exercises", []))
    if len(answers) != expected:
        raise ValueError(
            f"answers length {len(answers)} does not match exercises length {expected}"
        )
    exercises = data.get("exercises", [])
    if not isinstance(exercises, list) or not all(isinstance(ex, dict) for ex in exercises):
        raise ValueError(f"invalid koch-exercise exercises shape: {path}")
    claimed_set = data.get("claimed_set", [])
    claimed_set_size = len(claimed_set) if isinstance(claimed_set, list) else 0
    data["exercises"] = apply_answers_to_entries(
        list(exercises),
        list(answers),
        claimed_set_size=claimed_set_size,
    )
    serialised = json.dumps(data, indent=2).encode("utf-8")
    fd, tmp_path = tempfile.mkstemp(prefix=".record-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(serialised)
        os.replace(tmp_path, path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    return expected


def write_record(
    record: KochExerciseRecord | CadenceSendRecord | CopyKeyRecord,
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
