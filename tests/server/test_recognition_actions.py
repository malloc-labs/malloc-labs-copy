import random

from copy_653.server.recognition_actions import (
    ActiveRecognitionSession,
    _coerce_recognition_diagnostic,
    _coerce_recognition_exercise_completion,
    _generate_recognition_exercise,
    _recognition_answer_matches_target,
    _recognition_kind_for_gear,
    _say_after_for_slot,
)
from copy_653.audio.parameters import AudioParameters
from copy_653.config import RecognitionSettings


def test_recognition_gear_zero_generates_four_single_symbols():
    exercise = _generate_recognition_exercise(("K", "M"), gear=0, rng=random.Random(1))

    assert len(exercise) == 4
    assert all(len(word) == 1 for word in exercise)
    assert _recognition_kind_for_gear(0) == "single-symbols"


def test_recognition_gear_two_generates_symbol_pairs():
    exercise = _generate_recognition_exercise(("K", "M", "U"), gear=2, rng=random.Random(2))

    assert len(exercise) == 2
    assert all(len(word) == 2 for word in exercise)
    assert _recognition_kind_for_gear(2) == "pairs"


def test_recognition_gear_three_generates_words_up_to_three_symbols():
    exercise = _generate_recognition_exercise(("K", "M", "U"), gear=3, rng=random.Random(3))

    assert len(exercise) == 1
    assert all(len(word) == 3 for word in exercise)
    assert _recognition_kind_for_gear(3) == "words"


def test_recognition_gear_one_generates_one_symbol_pair():
    exercise = _generate_recognition_exercise(("K", "M", "U"), gear=1, rng=random.Random(4))

    assert len(exercise) == 1
    assert all(len(word) == 2 for word in exercise)
    assert _recognition_kind_for_gear(1) == "pairs"


def test_recognition_say_after_scaffold_by_gear_and_slot():
    assert _say_after_for_slot(gear=0, exercise_index=1) is True
    assert _say_after_for_slot(gear=0, exercise_index=5) is False
    assert _say_after_for_slot(gear=1, exercise_index=1) is False
    assert _say_after_for_slot(gear=1, exercise_index=3) is False
    assert _say_after_for_slot(gear=2, exercise_index=1) is False
    assert _say_after_for_slot(gear=3, exercise_index=1) is False


def test_recognition_answer_match_compacts_spacing():
    assert _recognition_answer_matches_target("R K", "RK")
    assert _recognition_answer_matches_target("rk", "R K")
    assert not _recognition_answer_matches_target("RU", "R K")


def test_complete_recognition_exercise_payload_is_strict():
    assert _coerce_recognition_exercise_completion(
        {
            "exercise_index": 2,
            "answer": "RK",
            "voice_capture": [{"t": 1.2, "text": "romeo kilo", "symbols": ["R", "K"]}],
        }
    ) == {
        "exercise_index": 2,
        "answer": "RK",
        "voice_capture": [{"t": 1.2, "text": "romeo kilo", "symbols": ["R", "K"]}],
    }
    assert (
        _coerce_recognition_exercise_completion(
            {"exercise_index": 2, "answer": "RK", "voice_capture": [[{"bad": "shape"}]]}
        )
        is None
    )


def test_recognition_diagnostic_payload_is_strict():
    assert _coerce_recognition_diagnostic(
        {
            "exercise_index": 2,
            "late_voice_capture": [
                {
                    "t": 2.4,
                    "text": "romeo",
                    "symbols": ["R"],
                    "reason": "after_committed_response",
                }
            ],
        }
    ) == {
        "exercise_index": 2,
        "late_voice_capture": [
            {
                "t": 2.4,
                "text": "romeo",
                "symbols": ["R"],
                "reason": "after_committed_response",
            }
        ],
    }
    assert (
        _coerce_recognition_diagnostic(
            {"exercise_index": 2, "late_voice_capture": [[{"bad": "shape"}]]}
        )
        is None
    )


def test_late_voice_capture_is_diagnostic_only(tmp_path):
    session = ActiveRecognitionSession(
        ws=None,  # type: ignore[arg-type]
        config_path=tmp_path / "config.toml",
        audio_params=AudioParameters(),
        claimed=("K", "M"),
        recognition_settings=RecognitionSettings(),
        anchors_dir=tmp_path,
        seed=1,
        set_session=1,
        set_id="test",
        gears=[1],
        rng=random.Random(1),
        exercises=[
            {
                "index": 1,
                "target": "M R",
                "answer": "M",
                "voice_capture": [{"t": 1.0, "text": "mike", "symbols": ["M"]}],
                "analysis": {"recognition_state": "low"},
            }
        ],
    )

    session.append_late_voice_capture(
        1,
        [{"t": 2.5, "text": "romeo", "symbols": ["R"], "reason": "after_committed_response"}],
    )

    assert session.exercises[0]["answer"] == "M"
    assert session.exercises[0]["voice_capture"] == [{"t": 1.0, "text": "mike", "symbols": ["M"]}]
    assert session.exercises[0]["late_voice_capture"] == [
        {"t": 2.5, "text": "romeo", "symbols": ["R"], "reason": "after_committed_response"}
    ]
