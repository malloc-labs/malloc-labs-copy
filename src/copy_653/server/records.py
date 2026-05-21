"""Session record writers for Koch and Cadence sessions (spec §5.1, §6.1).

Both writers are best-effort: a write failure is logged but does not
propagate. Truth that fails to land on disk is still truth the learner
heard, and the WS contract should not be held up by a slow filesystem.
This is one of the few places in the engine that deliberately swallows
exceptions; see the spec §6.1 rationale.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from copy_653.audio.parameters import AudioParameters
from copy_653.config import load_save_directory
from copy_653.sequence.cadence_analysis import (
    is_ready_for_next_symbol as cadence_is_ready_for_next_symbol,
    latest_gears_for_claimed_set as latest_cadence_gears_for_claimed_set,
    load_band_evidence as load_cadence_band_evidence,
    record_claimed_set_key as cadence_record_claimed_set_key,
    resolve_gears as resolve_cadence_gears,
)
from copy_653.sequence.exercise_analysis import (
    is_ready_for_next_symbol,
    latest_gears_for_claimed_set,
    load_band_evidence,
    resolve_gears,
)
from copy_653.session import (
    CadenceSendRecord,
    KochExerciseRecord,
    update_koch_answers,
    write_record,
)

logger = logging.getLogger(__name__)

# First soft gate on the listen-side next-symbol nudge: a per-claimed-set
# wall-clock floor. The existing readiness signal is band-evidence-based —
# it can flicker true after a single short, focused session, which the
# learner can read as "I know this set" even though the contact time is
# under a few minutes. The floor below holds the nudge back until at
# least an hour of practice on the *exact* claimed set has accumulated.
#
# Suggestion, not gate (philosophy §3.7): the learner can still claim
# any symbol they want; this only suppresses the highlight that *implies*
# they should. Note this only applies to the Koch listen-side; the Key
# send-side keeps its existing evidence-only behaviour for now.
MIN_SECONDS_PER_CLAIMED_SET = 60 * 60


class _ActiveCadenceSession:
    """In-flight Cadence (Key → Send) recording state for one WS connection."""

    __slots__ = (
        "started_at",
        "audio",
        "claimed",
        "request",
        "seed",
        "generation",
        "exercises",
        "sent",
        "key_events",
    )

    def __init__(
        self,
        *,
        started_at: datetime,
        audio: AudioParameters,
        claimed: tuple[str, ...],
        request: dict[str, Any],
        seed: int,
        generation: dict[str, Any],
        exercises: list[dict[str, Any]],
    ) -> None:
        self.started_at = started_at
        self.audio = audio
        self.claimed = claimed
        self.request = request
        self.seed = seed
        self.generation = generation
        self.exercises = exercises
        self.sent: list[dict[str, Any]] = []
        self.key_events: list[dict[str, Any]] = []

    def record_event(self, payload: dict[str, Any]) -> None:
        """Capture a relevant WS event payload into the session record."""
        kind = payload.get("type")
        if kind == "sent-symbol":
            self.sent.append(
                {
                    "symbol": payload["symbol"],
                    "pattern": payload["pattern"],
                    "started_at": payload["started_at"],
                    "ended_at": payload["ended_at"],
                    "leading_gap": payload["leading_gap"],
                }
            )
        elif kind == "key-event":
            entry = {
                "kind": payload["kind"],
                "note": payload["note"],
                "pressed": payload["pressed"],
                "timestamp": payload["timestamp"],
            }
            if "duration_ms" in payload:
                entry["duration_ms"] = payload["duration_ms"]
            if "ratio_dits" in payload:
                entry["ratio_dits"] = payload["ratio_dits"]
            self.key_events.append(entry)


def _finalize_cadence_session(
    session: _ActiveCadenceSession,
    config_path: Path,
) -> None:
    """Persist a Cadence session record. Best-effort; failures are logged."""
    if not session.sent and not session.key_events:
        # Nothing was keyed — no truth to record. Avoids leaving empty
        # files when a learner opens the page but never starts keying.
        return
    try:
        save_directory = load_save_directory(config_path)
        record = CadenceSendRecord(
            started_at=session.started_at,
            ended_at=datetime.now(timezone.utc),
            audio=session.audio,
            claimed_set=session.claimed,
            request=session.request,
            seed=session.seed,
            generation=session.generation,
            exercises=session.exercises,
            sent=session.sent,
            key_events=session.key_events,
        )
        write_record(record, save_directory)
    except Exception:
        logger.exception("failed to write cadence-send record")


def _save_koch_answers(path: Path, answers: list[str]) -> int:
    """Merge learner-typed answers into an existing koch-exercise record.

    Thin wrapper over :func:`update_koch_answers` that propagates the
    expected-exercise count back to the caller so it can be echoed on
    the success event. Errors propagate; the caller surfaces them as
    WS ``error`` frames per spec §1.5.
    """
    return update_koch_answers(path, answers)


def _iter_koch_records(save_directory: Path) -> list[dict[str, Any]]:
    """Load every parseable koch-exercise record under ``save_directory``.

    Returns full record dicts. Files that fail to parse or do not
    declare ``mode = "koch-exercise"`` are skipped — a corrupt file
    should not break the diagnostic or gear-resolution paths that
    consume this listing.
    """
    target_dir = save_directory / "koch-exercise"
    records: list[dict[str, Any]] = []
    if not target_dir.is_dir():
        return records
    for entry in target_dir.glob("koch-exercise-*.json"):
        try:
            data = json.loads(entry.read_text())
        except (OSError, ValueError):
            logger.exception("skipping unreadable koch-exercise record: %s", entry)
            continue
        if isinstance(data, dict) and data.get("mode") == "koch-exercise":
            records.append(data)
    return records


def _iter_cadence_records(save_directory: Path) -> list[dict[str, Any]]:
    """Load every parseable cadence-send record under ``save_directory``."""
    target_dir = save_directory / "cadence-send"
    records: list[dict[str, Any]] = []
    if not target_dir.is_dir():
        return records
    for entry in target_dir.glob("cadence-send-*.json"):
        try:
            data = json.loads(entry.read_text())
        except (OSError, ValueError):
            logger.exception("skipping unreadable cadence-send record: %s", entry)
            continue
        if isinstance(data, dict) and data.get("mode") == "cadence-send":
            records.append(data)
    return records


def _next_koch_run_index(save_directory: Path, claimed_set_key: str) -> int:
    """Return the next run index for sessions at this claimed-set key.

    Counts records that share the same normalised claimed-set identity.
    Legacy records that pre-date ``generation.claimed_set_key`` fall
    back to deriving the key from ``claimed_set`` so the count is
    consistent across the schema bump.
    """
    count = 0
    for data in _iter_koch_records(save_directory):
        generation = data.get("generation")
        key: str | None = None
        if isinstance(generation, dict):
            stored = generation.get("claimed_set_key")
            if isinstance(stored, str):
                key = stored
        if key is None:
            claimed = data.get("claimed_set")
            if isinstance(claimed, list):
                key = " ".join(sorted(str(s) for s in claimed))
        if key == claimed_set_key:
            count += 1
    return count + 1


def _resolve_session_gears(
    save_directory: Path, claimed_set_key: str, exercise_count: int
) -> list[int]:
    """Compute the per-slot gears for the next session.

    Reads recent koch-exercise records, derives per-band evidence and
    the most-recent session's gear floor, and applies the resolver to
    produce a list of gears parallel to ``exercise_count``. The list
    is returned with positional indices — entry ``i`` is the gear for
    slot ``i + 1``.
    """
    records = _iter_koch_records(save_directory)
    evidence = load_band_evidence(records, claimed_set_key=claimed_set_key)
    current_gears = latest_gears_for_claimed_set(records, claimed_set_key=claimed_set_key)
    resolved = resolve_gears(evidence, current_gears=current_gears)
    return [resolved.get(i + 1, 0) for i in range(exercise_count)]


def _seconds_on_claimed_set(records: list[dict[str, Any]], *, claimed_set_key: str) -> float:
    """Sum wall-clock seconds across records matching ``claimed_set_key``.

    Walks the same record list the readiness analysis already uses, so
    no extra disk read. Records with missing or invalid timestamps
    contribute 0, matching the calendar's client-side rule.

    Legacy records (pre-``generation.claimed_set_key``) are bucketed by
    deriving the key from ``claimed_set``, mirroring
    :func:`_next_koch_run_index`.
    """
    if not claimed_set_key:
        return 0.0
    total = 0.0
    for data in records:
        generation = data.get("generation")
        key: str | None = None
        if isinstance(generation, dict):
            stored = generation.get("claimed_set_key")
            if isinstance(stored, str):
                key = stored
        if key is None:
            claimed = data.get("claimed_set")
            if isinstance(claimed, list):
                key = " ".join(sorted(str(s) for s in claimed))
        if key != claimed_set_key:
            continue
        started_at = data.get("started_at")
        ended_at = data.get("ended_at")
        if not isinstance(started_at, str) or not isinstance(ended_at, str):
            continue
        try:
            start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        delta = (end - start).total_seconds()
        if delta > 0:
            total += delta
    return total


def _next_symbol_readiness(save_directory: Path, claimed_set_key: str) -> bool:
    """Whether saved evidence says the learner is ready for the next symbol.

    Thin disk-walking wrapper over :func:`is_ready_for_next_symbol`, with
    an additional per-claimed-set wall-clock floor (see
    :data:`MIN_SECONDS_PER_CLAIMED_SET`). Both signals must agree:
    band-evidence can satisfy the readiness analysis after a short
    focused session, but the time floor holds the nudge back until the
    learner has accumulated real contact time on this exact set.

    Returns ``False`` for an empty claimed-set key — the WS layer calls
    this for every ``claimed-symbols`` push and the empty key path is a
    real one (cold start before any claim).
    """
    if not claimed_set_key:
        return False
    records = _iter_koch_records(save_directory)
    if not is_ready_for_next_symbol(records, claimed_set_key=claimed_set_key):
        return False
    return (
        _seconds_on_claimed_set(records, claimed_set_key=claimed_set_key)
        >= MIN_SECONDS_PER_CLAIMED_SET
    )


def _next_send_symbol_readiness(save_directory: Path, claimed_set_key: str) -> bool:
    """Whether send-side evidence says the learner is ready for the next symbol.

    Send sibling of :func:`_next_symbol_readiness`. Reads ``cadence-send``
    records instead of ``koch-exercise``; the two readiness signals are
    independent on purpose so the listen and send sides of the
    curriculum can sit at different points (philosophy §3.7).
    """
    if not claimed_set_key:
        return False
    records = _iter_cadence_records(save_directory)
    return cadence_is_ready_for_next_symbol(records, claimed_set_key=claimed_set_key)


def _next_cadence_run_index(save_directory: Path, claimed_set_key: str) -> int:
    count = 0
    for data in _iter_cadence_records(save_directory):
        if cadence_record_claimed_set_key(data) == claimed_set_key:
            count += 1
    return count + 1


def _resolve_cadence_session_gears(
    save_directory: Path, claimed_set_key: str, exercise_count: int
) -> list[int]:
    records = _iter_cadence_records(save_directory)
    evidence = load_cadence_band_evidence(records, claimed_set_key=claimed_set_key)
    current_gears = latest_cadence_gears_for_claimed_set(records, claimed_set_key=claimed_set_key)
    resolved = resolve_cadence_gears(evidence, current_gears=current_gears)
    return [resolved.get(i + 1, 0) for i in range(exercise_count)]


def _write_koch_record(
    *,
    config_path: Path,
    audio_params: AudioParameters,
    claimed: tuple[str, ...],
    seed: int,
    generation: dict[str, Any],
    exercises: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    started_at: datetime,
) -> Path | None:
    """Persist a Koch Exercises session record (spec §5.1, §6.1).

    Best-effort: a write failure is logged and ``None`` is returned so
    the ``session-end`` signal still fires. Truth that fails to land on
    disk is still truth the learner heard.

    On success returns the resolved path; the caller stashes it so a
    later ``save-koch-answers`` can rewrite the same file with the
    learner's typed answers.
    """
    try:
        save_directory = load_save_directory(config_path)
        enriched = dict(generation)
        if "run_index" not in enriched:
            enriched["run_index"] = _next_koch_run_index(
                save_directory,
                str(enriched.get("claimed_set_key", "")),
            )
        record = KochExerciseRecord(
            started_at=started_at,
            ended_at=datetime.now(timezone.utc),
            audio=audio_params,
            claimed_set=claimed,
            seed=seed,
            generation=enriched,
            exercises=exercises,
            symbols=symbols,
        )
        return write_record(record, save_directory)
    except Exception:
        logger.exception("failed to write koch-exercise record")
        return None
