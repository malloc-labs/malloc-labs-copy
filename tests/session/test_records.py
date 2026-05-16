"""Tests for copy_653.session.records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from copy_653 import __version__
from copy_653.audio.parameters import AudioParameters
from copy_653.session.records import (
    SCHEMA_VERSION,
    CadenceSendRecord,
    KochExerciseRecord,
    write_record,
)


def _audio() -> AudioParameters:
    return AudioParameters()


def _koch_record(started_at: datetime | None = None) -> KochExerciseRecord:
    started = started_at or datetime(2026, 5, 15, 19, 30, 45, 123_000, tzinfo=timezone.utc)
    ended = datetime(2026, 5, 15, 19, 31, 15, 456_000, tzinfo=timezone.utc)
    return KochExerciseRecord(
        started_at=started,
        ended_at=ended,
        audio=_audio(),
        claimed_set=("K", "M", "U"),
        duration_seconds=30.0,
        seed=12345,
        symbols=[
            {"symbol": "K", "t_on": 0.0, "t_off": 0.18},
            {"symbol": "M", "t_on": 0.42, "t_off": 0.6},
        ],
    )


def _cadence_record(selection: dict | None = None) -> CadenceSendRecord:
    started = datetime(2026, 5, 15, 19, 30, 45, 123_000, tzinfo=timezone.utc)
    ended = datetime(2026, 5, 15, 19, 31, 15, 456_000, tzinfo=timezone.utc)
    return CadenceSendRecord(
        started_at=started,
        ended_at=ended,
        audio=_audio(),
        claimed_set=("K", "M", "U"),
        request={
            "exercise_count": 1,
            "min_words": 1,
            "max_words": 1,
            "min_word_length": 2,
            "max_word_length": 2,
        },
        seed=12345,
        exercises=["km"],
        sent=[
            {
                "symbol": "K",
                "pattern": "-.-",
                "started_at": 1.024,
                "ended_at": 1.910,
                "leading_gap": "none",
            }
        ],
        key_events=[
            {"kind": "dit", "note": 1, "pressed": True, "timestamp": 1.024},
            {"kind": "dit", "note": 1, "pressed": False, "timestamp": 1.110},
        ],
        selection=selection,
    )


def test_koch_record_shape_has_common_envelope(tmp_path: Path):
    path = write_record(_koch_record(), tmp_path)
    parsed = json.loads(path.read_text())

    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["engine_version"] == __version__
    assert parsed["mode"] == "koch-exercise"
    assert parsed["started_at"] == "2026-05-15T19:30:45.123Z"
    assert parsed["ended_at"] == "2026-05-15T19:31:15.456Z"
    assert parsed["claimed_set"] == ["K", "M", "U"]
    assert parsed["audio"]["character_speed_wpm"] == _audio().character_speed_wpm
    assert parsed["audio"]["sample_rate_hz"] == _audio().sample_rate_hz


def test_koch_record_carries_truth_timeline(tmp_path: Path):
    path = write_record(_koch_record(), tmp_path)
    parsed = json.loads(path.read_text())

    assert parsed["duration_seconds"] == 30.0
    assert parsed["seed"] == 12345
    assert parsed["symbols"] == [
        {"symbol": "K", "t_on": 0.0, "t_off": 0.18},
        {"symbol": "M", "t_on": 0.42, "t_off": 0.6},
    ]


def test_cadence_record_carries_exercises_sent_and_key_events(tmp_path: Path):
    path = write_record(_cadence_record(), tmp_path)
    parsed = json.loads(path.read_text())

    assert parsed["mode"] == "cadence-send"
    assert parsed["request"] == {
        "exercise_count": 1,
        "min_words": 1,
        "max_words": 1,
        "min_word_length": 2,
        "max_word_length": 2,
    }
    assert parsed["exercises"] == ["km"]
    assert parsed["sent"][0]["symbol"] == "K"
    assert parsed["sent"][0]["leading_gap"] == "none"
    assert parsed["key_events"][0] == {
        "kind": "dit",
        "note": 1,
        "pressed": True,
        "timestamp": 1.024,
    }


def test_schema_version_is_one_one():
    assert SCHEMA_VERSION == "1.1"


def test_cadence_selection_round_trips_when_present(tmp_path: Path):
    selection = {"candidate_count": 20, "scores": [23, 42, 61, 69, 133]}
    path = write_record(_cadence_record(selection=selection), tmp_path)
    parsed = json.loads(path.read_text())

    assert parsed["selection"] == selection


def test_cadence_selection_absent_when_not_provided(tmp_path: Path):
    path = write_record(_cadence_record(), tmp_path)
    parsed = json.loads(path.read_text())

    assert "selection" not in parsed


def test_koch_record_never_carries_selection(tmp_path: Path):
    path = write_record(_koch_record(), tmp_path)
    parsed = json.loads(path.read_text())

    assert "selection" not in parsed


def test_write_record_uses_per_mode_subdirectory(tmp_path: Path):
    koch_path = write_record(_koch_record(), tmp_path)
    cadence_path = write_record(_cadence_record(), tmp_path)

    assert koch_path.parent == tmp_path / "koch-exercise"
    assert cadence_path.parent == tmp_path / "cadence-send"
    assert koch_path.name == "koch-exercise-20260515T193045Z.json"
    assert cadence_path.name == "cadence-send-20260515T193045Z.json"


def test_write_record_suffixes_on_collision(tmp_path: Path):
    first = write_record(_koch_record(), tmp_path)
    second = write_record(_koch_record(), tmp_path)
    third = write_record(_koch_record(), tmp_path)

    assert first.name == "koch-exercise-20260515T193045Z.json"
    assert second.name == "koch-exercise-20260515T193045Z-1.json"
    assert third.name == "koch-exercise-20260515T193045Z-2.json"


def test_write_record_creates_save_directory_lazily(tmp_path: Path):
    fresh = tmp_path / "first-run" / "share" / "copy_653"
    assert not fresh.exists()

    path = write_record(_koch_record(), fresh)

    assert path.exists()
    assert path.parent == fresh / "koch-exercise"


def test_write_record_does_not_leave_temp_files_on_success(tmp_path: Path):
    write_record(_koch_record(), tmp_path)
    leftovers = list((tmp_path / "koch-exercise").glob(".record-*"))
    assert leftovers == []


@pytest.mark.parametrize(
    "when, expected",
    [
        (datetime(2026, 1, 2, 3, 4, 5, 0, tzinfo=timezone.utc), "2026-01-02T03:04:05.000Z"),
        (
            datetime(2026, 1, 2, 3, 4, 5, 999_000, tzinfo=timezone.utc),
            "2026-01-02T03:04:05.999Z",
        ),
    ],
)
def test_iso8601_format_has_millisecond_precision(tmp_path: Path, when: datetime, expected: str):
    record = _koch_record(started_at=when)
    parsed = json.loads(write_record(record, tmp_path).read_text())
    assert parsed["started_at"] == expected


# ---------- active cadence session (server-side accumulator) ----------


def test_active_cadence_session_filters_relevant_events():
    from copy_653.server.app import _ActiveCadenceSession

    session = _ActiveCadenceSession(
        started_at=datetime(2026, 5, 15, 19, 30, 45, tzinfo=timezone.utc),
        audio=_audio(),
        claimed=("K", "M"),
        request={"exercise_count": 1},
        seed=42,
        exercises=["k"],
    )

    # Relevant events accumulate.
    session.record_event(
        {
            "type": "key-event",
            "kind": "dit",
            "note": 1,
            "pressed": True,
            "timestamp": 1.0,
            "tone_frequency_hz": 600,
        }
    )
    session.record_event(
        {
            "type": "sent-symbol",
            "symbol": "K",
            "pattern": "-.-",
            "started_at": 1.0,
            "ended_at": 1.9,
            "leading_gap": "none",
        }
    )
    # Irrelevant events ignored.
    session.record_event({"type": "claimed-symbols", "symbols": ["K", "M"]})

    assert len(session.key_events) == 1
    assert session.key_events[0] == {
        "kind": "dit",
        "note": 1,
        "pressed": True,
        "timestamp": 1.0,
    }
    assert len(session.sent) == 1
    assert session.sent[0] == {
        "symbol": "K",
        "pattern": "-.-",
        "started_at": 1.0,
        "ended_at": 1.9,
        "leading_gap": "none",
    }
