"""MIDI note input for the reference TRRS Trinkey key path."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import threading
import time
from typing import Any

from copy_653.config import KeyerSettings
from copy_653.midi.key_decoder import KeyElement


@dataclass(frozen=True, slots=True)
class MidiNoteEvent:
    """One MIDI note state change at a monotonic timestamp."""

    note: int
    pressed: bool
    timestamp: float


def midi_message_to_note_event(message: Any, *, timestamp: float) -> MidiNoteEvent | None:
    """Convert a Mido note message into Copy's small note-event shape."""
    message_type = getattr(message, "type", None)
    if message_type not in {"note_on", "note_off"}:
        return None

    note = getattr(message, "note", None)
    if not isinstance(note, int) or isinstance(note, bool):
        return None

    if message_type == "note_off":
        pressed = False
    else:
        velocity = getattr(message, "velocity", 64)
        pressed = velocity != 0

    return MidiNoteEvent(note=note, pressed=pressed, timestamp=timestamp)


def key_element_from_note_event(
    event: MidiNoteEvent,
    settings: KeyerSettings,
) -> KeyElement | None:
    """Map the configured Trinkey note numbers to dit/dah elements."""
    if not event.pressed:
        return None
    if event.note == settings.dit_note:
        return KeyElement(kind="dit", timestamp=event.timestamp)
    if event.note == settings.dah_note:
        return KeyElement(kind="dah", timestamp=event.timestamp)
    return None


def iter_midi_note_events(
    *,
    port_name: str | None = None,
    poll_seconds: float = 0.005,
    clock: Callable[[], float] = time.monotonic,
    stop_event: threading.Event | None = None,
) -> Iterator[MidiNoteEvent]:
    """Yield note events from a Mido input port until ``stop_event`` is set.

    ``mido`` and its backend are imported lazily so the rest of Copy can
    run without MIDI dependencies until key input is actually requested.
    """
    import mido

    with mido.open_input(port_name) as inport:
        while stop_event is None or not stop_event.is_set():
            emitted = False
            for message in inport.iter_pending():
                event = midi_message_to_note_event(message, timestamp=clock())
                if event is not None:
                    emitted = True
                    yield event
            if not emitted:
                time.sleep(poll_seconds)
