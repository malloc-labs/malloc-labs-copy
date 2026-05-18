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
    update_koch_answers,
    write_record,
)
from copy_653.sequence.cadence_analysis import (
    build_cadence_exercise_entries,
    build_cadence_generation_profile,
)
from copy_653.sequence.exercise_analysis import build_exercise_entries, build_generation_profile


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
        seed=12345,
        generation=build_generation_profile(
            claimed_set=("K", "M", "U"),
            candidate_count=20,
            exercise_count=2,
        ),
        exercises=build_exercise_entries(["DE MK", "DE KMU"], scores=[32, 45]),
        symbols=[
            {
                "symbol": "M",
                "t_on": 0.0,
                "t_off": 0.18,
                "exercise_index": 1,
                "word_index": 1,
                "word": "mk",
            },
            {
                "symbol": "K",
                "t_on": 0.42,
                "t_off": 0.6,
                "exercise_index": 1,
                "word_index": 1,
                "word": "mk",
            },
            {
                "symbol": "K",
                "t_on": 1.2,
                "t_off": 1.38,
                "exercise_index": 2,
                "word_index": 1,
                "word": "kmu",
            },
        ],
    )


def _cadence_record() -> CadenceSendRecord:
    started = datetime(2026, 5, 15, 19, 30, 45, 123_000, tzinfo=timezone.utc)
    ended = datetime(2026, 5, 15, 19, 31, 15, 456_000, tzinfo=timezone.utc)
    return CadenceSendRecord(
        started_at=started,
        ended_at=ended,
        audio=_audio(),
        claimed_set=("K", "M", "U"),
        seed=12345,
        request={
            "exercise_count": 1,
            "min_words": 1,
            "max_words": 1,
            "min_word_length": 2,
            "max_word_length": 2,
        },
        generation=build_cadence_generation_profile(
            claimed_set=("K", "M", "U"),
            candidate_count=20,
            exercise_count=1,
        ),
        exercises=build_cadence_exercise_entries(["KM"], scores=[32]),
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
            {"kind": "dah", "note": 2, "pressed": True, "timestamp": 1.024},
            {"kind": "dah", "note": 2, "pressed": False, "timestamp": 1.204, "duration_ms": 180.0},
            {"kind": "dit", "note": 1, "pressed": True, "timestamp": 1.264},
            {"kind": "dit", "note": 1, "pressed": False, "timestamp": 1.324, "duration_ms": 60.0},
            {"kind": "dah", "note": 2, "pressed": True, "timestamp": 1.384},
            {"kind": "dah", "note": 2, "pressed": False, "timestamp": 1.564, "duration_ms": 180.0},
        ],
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

    assert parsed["seed"] == 12345
    assert parsed["generation"]["profile_version"] == "koch-burden-v1"
    assert parsed["generation"]["candidate_count"] == 20
    assert parsed["exercises"][0]["played"] == "DE MK"
    assert parsed["exercises"][0]["core"] == "MK"
    assert parsed["exercises"][0]["burden_score"] == 32
    assert parsed["exercises"][0]["burden_band"] == 1
    assert parsed["symbols"][0] == {
        "symbol": "M",
        "t_on": 0.0,
        "t_off": 0.18,
        "exercise_index": 1,
        "word_index": 1,
        "word": "mk",
    }
    assert parsed["symbols"][-1]["exercise_index"] == 2
    assert "duration_seconds" not in parsed


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
    assert parsed["generation"]["profile_version"] == "cadence-burden-v1"
    assert parsed["generation"]["candidate_count"] == 20
    assert parsed["exercises"][0]["target"] == "KM"
    assert parsed["exercises"][0]["analysis"]["saved"] is True
    assert parsed["sent"][0]["symbol"] == "K"
    assert parsed["sent"][0]["leading_gap"] == "none"
    assert parsed["key_events"][0] == {
        "kind": "dah",
        "note": 2,
        "pressed": True,
        "timestamp": 1.024,
    }


def test_schema_version_is_two_zero():
    assert SCHEMA_VERSION == "2.0"


def test_koch_record_serialises_unsaved_analysis(tmp_path: Path):
    path = write_record(_koch_record(), tmp_path)
    parsed = json.loads(path.read_text())
    assert "answers" not in parsed
    assert parsed["exercises"][0]["answer"] == ""
    assert parsed["exercises"][0]["analysis"] == {
        "version": "koch-analysis-v1",
        "saved": False,
    }


def test_koch_record_round_trips_filled_answers(tmp_path: Path):
    path = write_record(_koch_record(), tmp_path)
    update_koch_answers(path, ["DE MK", "DE KU"])
    parsed = json.loads(path.read_text())
    assert parsed["exercises"][0]["answer"] == "DE MK"
    assert parsed["exercises"][0]["analysis"]["saved"] is True
    assert parsed["exercises"][0]["analysis"]["band_state"] == "exact"
    assert parsed["exercises"][1]["answer"] == "DE KU"
    assert parsed["exercises"][1]["analysis"]["symbol_correct_units"] == 2


def test_update_koch_answers_rewrites_existing_file_in_place(tmp_path: Path):
    path = write_record(_koch_record(), tmp_path)
    expected = update_koch_answers(path, ["one", "two"])

    parsed = json.loads(path.read_text())
    assert parsed["exercises"][0]["answer"] == "one"
    assert parsed["exercises"][1]["answer"] == "two"
    # Length-of-exercises echoes back so the caller can confirm shape.
    assert expected == len(parsed["exercises"]) == 2
    # Truth fields are not disturbed.
    assert parsed["symbols"][0]["symbol"] == "M"
    assert parsed["seed"] == 12345


def test_update_koch_answers_rejects_length_mismatch(tmp_path: Path):
    path = write_record(_koch_record(), tmp_path)
    with pytest.raises(ValueError, match="does not match exercises length"):
        update_koch_answers(path, ["one"])  # record has 2 exercises


def test_update_koch_answers_rejects_non_koch_record(tmp_path: Path):
    path = write_record(_cadence_record(), tmp_path)
    with pytest.raises(ValueError, match="not a koch-exercise record"):
        update_koch_answers(path, ["x"])


def test_cadence_record_never_carries_selection(tmp_path: Path):
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
        generation=build_cadence_generation_profile(
            claimed_set=("K", "M"),
            candidate_count=20,
            exercise_count=1,
        ),
        exercises=build_cadence_exercise_entries(["K"], scores=[20]),
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
