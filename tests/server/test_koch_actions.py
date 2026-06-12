from copy_653.audio.parameters import AudioParameters
from copy_653.sequence.listening_conditions import (
    KOCH_PROBE_PHASE_CHALLENGE,
    KOCH_PROGRESSION_ROLE_SUPPORTING_GEAR_UP,
    listening_condition_for_session,
    rst_fields_for_audio_params,
)
from copy_653.server.koch_actions import (
    _apply_koch_listening_probe_metadata,
    _koch_challenge_rst_draws,
)


def test_koch_listening_condition_is_session_level():
    assert listening_condition_for_session(1) == "default"
    assert listening_condition_for_session(2) == "textured"
    assert listening_condition_for_session(3) == "default"


def test_koch_challenge_draws_are_bounded_worse_than_baseline():
    params = AudioParameters(receiver_bed=2, envelope_ramp_seconds=0.005)
    baseline = rst_fields_for_audio_params(params)

    draws = _koch_challenge_rst_draws(params, exercise_count=5, seed=123)

    assert len(draws) == 5
    assert draws == _koch_challenge_rst_draws(params, exercise_count=5, seed=123)
    for s, t in draws:
        assert max(1, baseline["s"] - 3) <= s <= max(1, baseline["s"] - 1)
        assert max(1, baseline["t"] - 3) <= t <= max(1, baseline["t"] - 1)


def test_koch_probe_metadata_stores_challenge_role_and_rst_fields():
    entries = _apply_koch_listening_probe_metadata(
        [
            {"index": 1, "played": "DE KM", "answer": ""},
            {"index": 2, "played": "DE MK", "answer": ""},
        ],
        rst_draws=[(6, 2), (5, 1)],
    )

    assert entries[0]["listening_probe"] == "koch-listening-conditions-v1"
    assert entries[0]["listening_condition"] == "textured"
    assert entries[0]["probe_phase"] == KOCH_PROBE_PHASE_CHALLENGE
    assert entries[0]["progression_role"] == KOCH_PROGRESSION_ROLE_SUPPORTING_GEAR_UP
    assert entries[0]["s"] == 6
    assert entries[0]["t"] == 2
    assert entries[1]["s"] == 5
    assert entries[1]["t"] == 1
