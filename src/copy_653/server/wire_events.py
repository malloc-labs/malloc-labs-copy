"""Outbound WebSocket event payload builders.

Pure functions and one thin send helper. Every payload the engine pushes
to the UI is constructed here so the wire-protocol surface (documented
in :mod:`copy_653.server.app`) is read from one place. Adding a new
event type means adding one builder here, not editing an action.

These builders are deliberately stateless. The action coroutines own
session state and call into these to materialise frames.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol

from copy_653.audio import patterns, texture, timing
from copy_653.audio.parameters import AudioParameters
from copy_653.config import DEFAULT_CONFIG_PATH, DeveloperSettings, KeyerSettings
from copy_653.midi import DecodedSymbol, KeyElement, MidiNoteEvent

logger = logging.getLogger(__name__)


async def _send_event(ws: WebSocketServerProtocol, event: dict[str, Any]) -> None:
    """Serialise ``event`` to JSON and send it on ``ws``.

    Swallows :class:`ConnectionClosed` because a learner closing the
    tab mid-session is normal, not an error. Other exceptions
    propagate per spec §1.5.
    """
    try:
        await ws.send(json.dumps(event))
    except ConnectionClosed:
        pass


def _claimed_symbols_event(claimed: tuple[str, ...]) -> dict[str, Any]:
    """Build the ``claimed-symbols`` event payload from a claimed list."""
    return {
        "type": "claimed-symbols",
        "symbols": list(claimed),
        "suggested_next": patterns.next_koch_after(claimed),
    }


def _sent_symbol_event(decoded: DecodedSymbol) -> dict[str, Any]:
    """Build the Key page event for a decoded sent symbol."""
    return {
        "type": "sent-symbol",
        "symbol": decoded.symbol,
        "pattern": decoded.pattern,
        "started_at": decoded.started_at,
        "ended_at": decoded.ended_at,
        "leading_gap": decoded.leading_gap,
    }


def _key_input_start_event(settings: KeyerSettings, params: AudioParameters) -> dict[str, Any]:
    """Build the Key page event announcing active MIDI input."""
    return _key_input_start_payload(
        settings,
        params,
        input_name=settings.input_name,
        source="server",
    )


def _key_input_start_payload(
    settings: KeyerSettings,
    params: AudioParameters,
    *,
    input_name: str | None,
    source: str,
) -> dict[str, Any]:
    """Build the Key page event announcing active key input."""
    dit_seconds = timing.dit_seconds(params.character_speed_wpm)
    character_gap_seconds = timing.send_inter_character_seconds(params.character_speed_wpm)
    word_gap_seconds = timing.send_inter_word_seconds(params.character_speed_wpm)
    return {
        "type": "key-input-start",
        "source": source,
        "input_name": input_name,
        "dit_note": settings.dit_note,
        "dah_note": settings.dah_note,
        "straight_note": settings.straight_note,
        "trinkey_buzzer_enabled": settings.trinkey_buzzer_enabled,
        "character_wpm": params.character_speed_wpm,
        "effective_wpm": params.effective_speed_wpm,
        "tone_frequency_hz": params.tone_frequency_hz,
        "amplitude": params.amplitude,
        "envelope_ramp_ms": round(params.envelope_ramp_seconds * 1000, 3),
        "dit_ms_expected": round(dit_seconds * 1000, 3),
        "character_gap_ms": round(character_gap_seconds * 1000, 3),
        "word_gap_ms": round(word_gap_seconds * 1000, 3),
    }


def _audio_settings_event_from_params(
    params: AudioParameters,
    keyer_settings: KeyerSettings | None = None,
    developer_settings: DeveloperSettings | None = None,
    save_directory: Path | None = None,
) -> dict[str, Any]:
    """Build the learner-facing audio timing event payload."""
    if keyer_settings is None:
        keyer_settings = KeyerSettings()
    if developer_settings is None:
        developer_settings = DeveloperSettings()
    if save_directory is None:
        save_directory = DEFAULT_CONFIG_PATH.parent
    return {
        "type": "audio-settings",
        "character_wpm": params.character_speed_wpm,
        "effective_wpm": params.effective_speed_wpm,
        "farnsworth_enabled": params.effective_speed_wpm < params.character_speed_wpm,
        "tone_shape": texture.tone_shape_for_envelope_seconds(params.envelope_ramp_seconds),
        "receiver_bed": params.receiver_bed,
        "cadence_variation": params.cadence_variation,
        "trinkey_buzzer_enabled": keyer_settings.trinkey_buzzer_enabled,
        "keyer_mode": keyer_settings.keyer_mode,
        "hh_clear_enabled": developer_settings.hh_clear_enabled,
        "save_directory": str(save_directory),
    }


def _key_event_event(
    event: MidiNoteEvent,
    settings: KeyerSettings,
    params: AudioParameters,
    element: KeyElement | None = None,
) -> dict[str, Any] | None:
    """Build a live key press/release event for diagnostics and browser sidetone."""
    if event.note == settings.dit_note:
        kind = "dit"
    elif event.note == settings.dah_note:
        kind = "dah"
    elif event.note == settings.straight_note:
        kind = "straight"
    else:
        return None

    payload: dict[str, Any] = {
        "type": "key-event",
        "kind": kind,
        "note": event.note,
        "pressed": event.pressed,
        "timestamp": event.timestamp,
        "tone_frequency_hz": params.tone_frequency_hz,
        "amplitude": params.amplitude,
        "envelope_ramp_ms": round(params.envelope_ramp_seconds * 1000, 3),
        "trinkey_buzzer_enabled": settings.trinkey_buzzer_enabled,
    }
    if element is not None:
        duration_seconds = element.ended_at - element.started_at
        dit_seconds = timing.dit_seconds(params.character_speed_wpm)
        payload["duration_ms"] = round(duration_seconds * 1000, 3)
        payload["ratio_dits"] = round(duration_seconds / dit_seconds, 3)
    return payload
