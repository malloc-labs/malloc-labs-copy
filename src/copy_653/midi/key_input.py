"""MIDI note input for the reference TRRS Trinkey key path."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import queue
import threading
import time
from typing import Any

from copy_653.config import KeyerSettings
from copy_653.midi.key_decoder import ElementKind, KeyElement


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
    """Map a note-on event to a zero-duration element.

    Kept for compatibility with older tests and callers. Live input should
    use :class:`KeyElementAssembler` so note-off timing is preserved.
    """
    if not event.pressed:
        return None
    if event.note == settings.dit_note:
        return KeyElement(kind="dit", started_at=event.timestamp, ended_at=event.timestamp)
    if event.note == settings.dah_note:
        return KeyElement(kind="dah", started_at=event.timestamp, ended_at=event.timestamp)
    return None


class KeyElementAssembler:
    """Build completed key elements from MIDI note-on/off pairs."""

    def __init__(self) -> None:
        self._active: dict[int, tuple[ElementKind, float]] = {}

    def push(self, event: MidiNoteEvent, settings: KeyerSettings) -> KeyElement | None:
        kind = _kind_for_note(event.note, settings)
        if kind is None:
            return None

        if event.pressed:
            self._active[event.note] = (kind, event.timestamp)
            return None

        active = self._active.pop(event.note, None)
        if active is None:
            return None

        started_kind, started_at = active
        return KeyElement(kind=started_kind, started_at=started_at, ended_at=event.timestamp)


def _kind_for_note(note: int, settings: KeyerSettings) -> ElementKind | None:
    if note == settings.dit_note:
        return "dit"
    if note == settings.dah_note:
        return "dah"
    return None


def iter_midi_note_events(
    *,
    port_name: str | None = None,
    clock: Callable[[], float] = time.monotonic,
    stop_event: threading.Event | None = None,
) -> Iterator[MidiNoteEvent]:
    """Yield note events from a Mido input port until ``stop_event`` is set.

    Uses Mido's callback mode so each message is timestamped on the reader
    thread within microseconds of arriving from rtmidi, not at the next
    consumer poll wake-up. Stamping at arrival preserves CoreMIDI's
    high-precision timing through to the decoder.

    ``mido`` and its backend are imported lazily so the rest of Copy can
    run without MIDI dependencies until key input is actually requested.
    """
    import mido

    resolved_port_name = resolve_midi_input_name(mido.get_input_names(), port_name)
    events: queue.Queue[MidiNoteEvent] = queue.Queue()

    def _on_message(message: Any) -> None:
        # Fires on mido's reader thread. Keep the work minimal: stamp,
        # convert, enqueue. Anything heavier here would re-introduce the
        # arrival-time jitter callback mode is meant to eliminate.
        note_event = midi_message_to_note_event(message, timestamp=clock())
        if note_event is not None:
            events.put_nowait(note_event)

    with mido.open_input(resolved_port_name, callback=_on_message):
        while stop_event is None or not stop_event.is_set():
            try:
                # Short timeout so stop_event is checked promptly on shutdown.
                yield events.get(timeout=0.1)
            except queue.Empty:
                continue


def resolve_midi_input_name(
    input_names: list[str],
    preferred_name: str | None,
) -> str | None:
    """Resolve a configured MIDI input name to a concrete Mido port name.

    Mido expects the concrete CoreMIDI/ALSA port name. The config accepts
    a stable substring such as ``TRRS Trinkey`` so the default can match
    observed names like ``TRRS Trinkey M0``.
    """
    if preferred_name is None:
        return None

    preferred = preferred_name.strip()
    if not preferred:
        return None

    for name in input_names:
        if name == preferred:
            return name

    lowered = preferred.lower()
    for name in input_names:
        if lowered in name.lower():
            return name

    available = ", ".join(input_names) or "none"
    raise ValueError(f"MIDI input matching {preferred!r} not found; available inputs: {available}")
