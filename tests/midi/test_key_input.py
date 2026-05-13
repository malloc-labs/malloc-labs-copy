"""Tests for MIDI note input mapping."""

from __future__ import annotations

from types import SimpleNamespace

from copy_653.config import KeyerSettings
from copy_653.midi import (
    KeyElement,
    KeyElementAssembler,
    MidiNoteEvent,
    key_element_from_note_event,
    midi_message_to_note_event,
    resolve_midi_input_name,
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
    assert (
        key_element_from_note_event(
            MidiNoteEvent(note=2, pressed=True, timestamp=2.0),
            settings,
        ).ended_at
        == 2.0
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


def test_key_element_assembler_uses_note_on_and_note_off_times():
    settings = KeyerSettings(dit_note=1, dah_note=2)
    assembler = KeyElementAssembler()

    assert assembler.push(MidiNoteEvent(note=2, pressed=True, timestamp=1.0), settings) is None
    assert assembler.push(MidiNoteEvent(note=2, pressed=False, timestamp=1.18), settings) == (
        KeyElement(kind="dah", started_at=1.0, ended_at=1.18)
    )


def test_key_element_assembler_ignores_release_without_press():
    settings = KeyerSettings(dit_note=1, dah_note=2)
    assembler = KeyElementAssembler()

    assert assembler.push(MidiNoteEvent(note=1, pressed=False, timestamp=1.0), settings) is None


def test_resolve_midi_input_name_accepts_exact_match():
    assert (
        resolve_midi_input_name(
            ["SSL 2+ Mk II", "TRRS Trinkey M0"],
            "TRRS Trinkey M0",
        )
        == "TRRS Trinkey M0"
    )


def test_resolve_midi_input_name_accepts_substring_match():
    assert (
        resolve_midi_input_name(
            ["SSL 2+ Mk II", "TRRS Trinkey M0"],
            "TRRS Trinkey",
        )
        == "TRRS Trinkey M0"
    )


def test_resolve_midi_input_name_returns_default_input_when_unconfigured():
    assert resolve_midi_input_name(["TRRS Trinkey M0"], None) is None


def test_resolve_midi_input_name_reports_available_inputs():
    try:
        resolve_midi_input_name(["SSL 2+ Mk II", "IAC Driver Bus 1"], "TRRS Trinkey")
    except ValueError as exc:
        assert "TRRS Trinkey" in str(exc)
        assert "SSL 2+ Mk II" in str(exc)
    else:
        raise AssertionError("expected ValueError")
