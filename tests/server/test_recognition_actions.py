import asyncio
import json
import random

import pytest

from copy_653.server.recognition_actions import (
    ActiveRecognitionSession,
    _audio_params_for_gear,
    _audio_params_for_listening_condition,
    _audio_params_for_recognition_set,
    _audio_params_for_rhythm_probe,
    _coerce_recognition_diagnostic,
    _coerce_recognition_exercise_completion,
    _generate_recognition_exercise,
    _is_rhythm_probe_exercise,
    _listening_condition_for_session,
    _play_recognition_exercise,
    _recognition_floor_samples,
    _recognition_exercise_entry,
    _run_recognition_session,
    _recognition_answer_matches_target,
    _recognition_kind_for_gear,
    _rst_for_recognition_set,
    _rst_fields_for_audio_params,
    _say_after_for_slot,
    _should_run_rhythm_probe,
)
from copy_653.audio.parameters import AudioParameters
from copy_653.config import RecognitionSettings


class _CaptureWs:
    def __init__(self):
        self.events = []

    async def send(self, payload):
        self.events.append(json.loads(payload))


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


def test_recognition_page_floor_generates_non_silent_bed():
    samples = _recognition_floor_samples(
        AudioParameters(sample_rate_hz=100, receiver_bed=2, cadence_variation=0)
    )

    assert len(samples) == 3000
    assert samples.any()


def test_recognition_exercise_entry_stores_effective_rst_fields():
    entry = _recognition_exercise_entry(
        1,
        ["K", "M"],
        3,
        audio_params=AudioParameters(receiver_bed=2, envelope_ramp_seconds=0.005),
    )

    assert entry["s"] == 7
    assert entry["t"] == 3


def test_recognition_exercise_entry_stores_listening_probe_metadata():
    params = _audio_params_for_listening_condition(
        AudioParameters(receiver_bed=2, envelope_ramp_seconds=0.005),
        _listening_condition_for_session(2),
    )
    entry = _recognition_exercise_entry(
        2,
        ["K", "M"],
        0,
        audio_params=params,
        listening_condition="textured",
    )

    assert entry["listening_probe"] == "recognition-listening-conditions-v1"
    assert entry["listening_condition"] == "textured"
    assert entry["s"] == 7
    assert entry["t"] == 5


def test_recognition_exercise_entry_stores_rhythm_probe_metadata():
    params = _audio_params_for_rhythm_probe(AudioParameters(cadence_variation=1))
    entry = _recognition_exercise_entry(
        3,
        ["K", "M"],
        1,
        audio_params=params,
        baseline_cadence_variation=1,
    )

    assert entry["rhythm_probe"] == "recognition-rhythm-v1"
    assert entry["baseline_cadence_variation"] == 1
    assert entry["cadence_variation"] == 2


def test_recognition_rhythm_probe_uses_third_exercise_after_grace_slot():
    assert not _should_run_rhythm_probe(set_session=3, exercise_index=1, is_retry=False)
    assert not _should_run_rhythm_probe(set_session=3, exercise_index=2, is_retry=False)
    assert _should_run_rhythm_probe(set_session=3, exercise_index=3, is_retry=False)
    assert not _should_run_rhythm_probe(set_session=3, exercise_index=3, is_retry=True)
    assert _is_rhythm_probe_exercise(3, 3)


def test_recognition_listening_condition_is_session_level():
    assert _listening_condition_for_session(1) == "default"
    assert _listening_condition_for_session(2) == "textured"
    assert _listening_condition_for_session(3) == "default"


def test_recognition_set_rst_ramp_degrades_from_configured_baseline():
    params = AudioParameters(receiver_bed=2, envelope_ramp_seconds=0.007)

    assert [_rst_for_recognition_set(params, idx) for idx in range(1, 9)] == [
        (7, 3),
        (6, 3),
        (6, 2),
        (5, 2),
        (5, 2),
        (4, 2),
        (4, 1),
        (3, 1),
    ]


def test_recognition_set_rst_ramp_updates_effective_audio_params():
    params = _audio_params_for_recognition_set(
        AudioParameters(receiver_bed=2, envelope_ramp_seconds=0.007),
        8,
    )

    assert _rst_fields_for_audio_params(params) == {"s": 3, "t": 1}


def test_recognition_set_one_preserves_configured_audio_params():
    base = AudioParameters(
        receiver_bed=2,
        envelope_ramp_seconds=0.007,
        tone_distortion=0.0,
        tone_ripple=0.0,
    )

    assert _audio_params_for_recognition_set(base, 1) == base


def test_default_recognition_probe_keeps_configured_texture():
    params = _audio_params_for_listening_condition(
        AudioParameters(receiver_bed=2, envelope_ramp_seconds=0.007),
        _listening_condition_for_session(1),
    )
    entry = _recognition_exercise_entry(
        1,
        ["K", "M"],
        0,
        audio_params=params,
        listening_condition="default",
    )

    assert entry["listening_condition"] == "default"
    assert entry["s"] == 7
    assert entry["t"] == 3


def test_recognition_rst_fields_reflect_gear_floor_override():
    base = AudioParameters(receiver_bed=0, envelope_ramp_seconds=0.005)

    assert _rst_fields_for_audio_params(base)["s"] == 9
    assert _rst_fields_for_audio_params(_audio_params_for_gear(base, 3))["s"] == 7


def test_recognition_exercise_playback_leaves_floor_to_page_loop(tmp_path, monkeypatch):
    ws = _CaptureWs()
    session = ActiveRecognitionSession(
        ws=ws,  # type: ignore[arg-type]
        config_path=tmp_path / "config.toml",
        audio_params=AudioParameters(receiver_bed=2),
        claimed=("K", "M"),
        recognition_settings=RecognitionSettings(
            say_before=False,
            morse_count=1,
            recognition_time_ms=0,
            say_after=False,
        ),
        anchors_dir=tmp_path,
        seed=1,
        set_session=1,
        set_id="test",
        gears=[0],
        rng=random.Random(1),
    )
    played = []

    def fail_if_exercise_adds_receiver_bed(*_args, **_kwargs):
        raise AssertionError("recognition exercise playback should not mix receiver bed")

    monkeypatch.setattr(
        "copy_653.server.recognition_actions.texture.add_receiver_bed",
        fail_if_exercise_adds_receiver_bed,
    )
    monkeypatch.setattr(
        "copy_653.server.recognition_actions._play_samples",
        lambda samples, sample_rate_hz, output_device: played.append((samples, sample_rate_hz)),
    )
    monkeypatch.setattr(
        "copy_653.server.recognition_actions.GAP_BETWEEN_SYMBOLS_SECONDS",
        0,
    )

    asyncio.run(_play_recognition_exercise(session, exercise=["K"], exercise_index=1))

    assert len(played) == 1
    assert any(event["type"] == "symbol" and event["symbol"] == "K" for event in ws.events)


def test_textured_recognition_probe_uses_page_floor_without_extra_bed(tmp_path, monkeypatch):
    ws = _CaptureWs()
    session = ActiveRecognitionSession(
        ws=ws,  # type: ignore[arg-type]
        config_path=tmp_path / "config.toml",
        audio_params=AudioParameters(receiver_bed=2),
        claimed=("K", "M"),
        recognition_settings=RecognitionSettings(
            say_before=False,
            morse_count=1,
            recognition_time_ms=0,
            say_after=False,
        ),
        anchors_dir=tmp_path,
        seed=1,
        set_session=1,
        set_id="test",
        gears=[0],
        rng=random.Random(1),
    )

    def fail_if_textured_adds_receiver_bed(*_args, **_kwargs):
        raise AssertionError("textured listening probe should keep the loaded page floor")

    monkeypatch.setattr(
        "copy_653.server.recognition_actions.texture.add_receiver_bed",
        fail_if_textured_adds_receiver_bed,
    )
    monkeypatch.setattr(
        "copy_653.server.recognition_actions._play_samples",
        lambda _samples, _sample_rate_hz, _output_device: None,
    )
    monkeypatch.setattr(
        "copy_653.server.recognition_actions.GAP_BETWEEN_SYMBOLS_SECONDS",
        0,
    )

    params = _audio_params_for_listening_condition(
        AudioParameters(receiver_bed=2),
        "textured",
    )
    asyncio.run(
        _play_recognition_exercise(
            session,
            exercise=["K"],
            exercise_index=2,
            audio_params=params,
        )
    )


def test_default_recognition_probe_does_not_add_extra_exercise_bed(tmp_path, monkeypatch):
    ws = _CaptureWs()
    session = ActiveRecognitionSession(
        ws=ws,  # type: ignore[arg-type]
        config_path=tmp_path / "config.toml",
        audio_params=AudioParameters(receiver_bed=2),
        claimed=("K", "M"),
        recognition_settings=RecognitionSettings(
            say_before=False,
            morse_count=1,
            recognition_time_ms=0,
            say_after=False,
        ),
        anchors_dir=tmp_path,
        seed=1,
        set_session=1,
        set_id="test",
        gears=[0],
        rng=random.Random(1),
    )

    def fail_if_default_adds_receiver_bed(*_args, **_kwargs):
        raise AssertionError("default listening probe should use the page floor only")

    monkeypatch.setattr(
        "copy_653.server.recognition_actions.texture.add_receiver_bed",
        fail_if_default_adds_receiver_bed,
    )
    monkeypatch.setattr(
        "copy_653.server.recognition_actions._play_samples",
        lambda _samples, _sample_rate_hz, _output_device: None,
    )
    monkeypatch.setattr(
        "copy_653.server.recognition_actions.GAP_BETWEEN_SYMBOLS_SECONDS",
        0,
    )

    params = _audio_params_for_listening_condition(
        AudioParameters(receiver_bed=2),
        "default",
    )
    asyncio.run(
        _play_recognition_exercise(
            session,
            exercise=["K"],
            exercise_index=1,
            audio_params=params,
        )
    )


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


def test_recognition_session_start_announces_gear_and_kind(tmp_path, monkeypatch):
    ws = _CaptureWs()
    session = ActiveRecognitionSession(
        ws=ws,  # type: ignore[arg-type]
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
    )

    def stop_after_start(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(
        "copy_653.server.recognition_actions._generate_recognition_exercise",
        stop_after_start,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run_recognition_session(session))

    assert ws.events[0]["type"] == "session-start"
    assert ws.events[0]["gear"] == 1
    assert ws.events[0]["recognition_kind"] == "pairs"
    assert ws.events[0]["listening_condition"] == "default"
    assert ws.events[0]["s"] == 7
    assert ws.events[0]["t"] == 3
