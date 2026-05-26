"""Compatibility helpers for persisted session records.

Older saved records remain valid input for the settings UI and analysis
endpoints. This module holds on-read normalisation so transport layers can
serve those records without carrying schema-specific backfill details.
"""

from __future__ import annotations

from typing import Any

from copy_653.sequence.cadence_analysis import apply_copy_key_analysis


def backfill_copy_key_record(data: dict[str, Any]) -> dict[str, Any]:
    """Return ``data`` with copy-key exercise analysis present when possible.

    Records written before copy-key analysis was finalized may contain raw
    exercise, sent, and key-event streams without saved per-exercise analysis.
    Current writers already persist that analysis, so this helper is an
    idempotent compatibility path for older records loaded from disk.
    """
    exercises = data.get("exercises")
    if not isinstance(exercises, list) or not exercises:
        return data

    first = exercises[0] if isinstance(exercises[0], dict) else {}
    if (first.get("analysis") or {}).get("saved"):
        return data

    audio = data.get("audio") or {}
    data["exercises"] = apply_copy_key_analysis(
        exercises,
        sent=data.get("sent") or [],
        key_events=data.get("key_events") or [],
        character_wpm=audio.get("character_speed_wpm", 20),
    )
    return data


def backfill_copy_key_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply copy-key compatibility backfill to a batch of records."""
    for record in records:
        backfill_copy_key_record(record)
    return records
