"""Tests for MIDI note input mapping."""

from __future__ import annotations

from types import SimpleNamespace

from copy_653.config import KeyerSettings
from copy_653.midi import (
    MidiNoteEvent,
    key_element_from_note_event,
    midi_message_to_note_event,
)


def test_midi_message_to_note_event_accepts_note_on():
    event = midi_message_to_note_event(
        SimpleNamespace(type="note_on", note=1, velocity=127),
        timestamp=12.3,
    )

    assert event == MidiNoteEvent(note=1, pressed=True, timestamp=12.3)


def test_midi_message_to_note_event_treats_zero_velocity_as_release():
    event = midi_message_to_note_event(
        SimpleNamespace(type="note_on", note=1, velocity=0),
        timestamp=12.3,
    )

    assert event == MidiNoteEvent(note=1, pressed=False, timestamp=12.3)


def test_midi_message_to_note_event_ignores_non_note_messages():
    assert (
        midi_message_to_note_event(
            SimpleNamespace(type="control_change", note=1, velocity=127),
            timestamp=12.3,
        )
        is None
    )


def test_key_element_from_note_event_maps_configured_dit_and_dah():
    settings = KeyerSettings(dit_note=1, dah_note=2)

    assert (
        key_element_from_note_event(
            MidiNoteEvent(note=1, pressed=True, timestamp=1.0),
            settings,
        ).kind
        == "dit"
    )
    assert (
        key_element_from_note_event(
            MidiNoteEvent(note=2, pressed=True, timestamp=2.0),
            settings,
        ).kind
        == "dah"
    )


def test_key_element_from_note_event_ignores_releases_and_other_notes():
    settings = KeyerSettings(dit_note=1, dah_note=2)

    assert (
        key_element_from_note_event(MidiNoteEvent(note=1, pressed=False, timestamp=1.0), settings)
        is None
    )
    assert (
        key_element_from_note_event(MidiNoteEvent(note=60, pressed=True, timestamp=1.0), settings)
        is None
    )
