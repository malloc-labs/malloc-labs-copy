"""Inbound WebSocket message parsers.

Pure validation/coercion of client-supplied JSON values. Each helper
either returns a well-typed value or raises :class:`ValueError`; action
coroutines catch the error and turn it into a ``{"type": "error",
"reason": "…"}`` frame per spec §1.5.

These helpers are deliberately strict — ``bool`` is rejected wherever
an ``int`` is expected (``isinstance(True, int)`` is ``True`` in Python
but the wire protocol means them differently).
"""

from __future__ import annotations

import logging
from typing import Any

from copy_653.audio import texture
from copy_653.audio.parameters import AudioParameters
from copy_653.midi import MidiNoteEvent

logger = logging.getLogger(__name__)


def _strict_positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _strict_bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    parsed = _optional_bounded_int(value, field, minimum, maximum)
    if parsed is None:
        raise ValueError(f"{field} must be an integer from {minimum} to {maximum}")
    return parsed


def _optional_bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer from {minimum} to {maximum}")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer from {minimum} to {maximum}")
    return value


def _optional_positive_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _optional_bool(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _optional_non_empty_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} must not be empty")
    return stripped


def _audio_params_from_settings_message(message: dict[str, Any]) -> AudioParameters:
    character_wpm = _strict_positive_int(message.get("character_wpm"), "character_wpm")
    effective_wpm = _strict_positive_int(message.get("effective_wpm"), "effective_wpm")
    tone_shape = _strict_bounded_int(
        message.get("tone_shape"),
        "tone_shape",
        texture.MIN_TONE_SHAPE,
        texture.MAX_TONE_SHAPE,
    )
    receiver_bed = _strict_bounded_int(
        message.get("receiver_bed"),
        "receiver_bed",
        texture.MIN_RECEIVER_BED,
        texture.MAX_RECEIVER_BED,
    )
    cadence_variation = _strict_bounded_int(
        message.get("cadence_variation"),
        "cadence_variation",
        texture.MIN_CADENCE_VARIATION,
        texture.MAX_CADENCE_VARIATION,
    )
    return AudioParameters(
        character_speed_wpm=character_wpm,
        effective_speed_wpm=effective_wpm,
        envelope_ramp_seconds=texture.envelope_seconds_for_tone_shape(tone_shape),
        receiver_bed=receiver_bed,
        cadence_variation=cadence_variation,
    )


def _browser_midi_note_event(
    message: dict[str, Any],
    *,
    fallback_timestamp: float,
    clock_offset: float | None = None,
) -> MidiNoteEvent:
    """Build a ``MidiNoteEvent`` from a browser ``key-note-event`` message.

    ``clock_offset`` shifts the incoming timestamp (browser ``performance.now()``
    domain) into the server's ``time.monotonic()`` domain so element
    timestamps and timer-driven flushes live in one clock. The offset is
    captured once per browser key-input session in
    ``start-browser-key-input`` and applied to every subsequent event.
    """
    note = message.get("note")
    pressed = message.get("pressed")
    timestamp = message.get("timestamp", fallback_timestamp)

    if not isinstance(note, int) or isinstance(note, bool) or not 0 <= note <= 127:
        raise ValueError("note must be a MIDI note from 0 to 127")
    if not isinstance(pressed, bool):
        raise ValueError("pressed must be a boolean")
    if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
        raise ValueError("timestamp must be numeric")

    monotonic_timestamp = float(timestamp)
    if clock_offset is not None and "timestamp" in message:
        monotonic_timestamp += clock_offset

    return MidiNoteEvent(note=note, pressed=pressed, timestamp=monotonic_timestamp)
