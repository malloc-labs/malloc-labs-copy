"""Shared listening-condition probe constants and audio helpers."""

from __future__ import annotations

from dataclasses import replace

from copy_653.audio import texture
from copy_653.audio.parameters import AudioParameters

RECOGNITION_LISTENING_PROBE_VERSION = "recognition-listening-conditions-v1"
KOCH_LISTENING_PROBE_VERSION = "koch-listening-conditions-v1"
LISTENING_CONDITION_DEFAULT = "default"
LISTENING_CONDITION_TEXTURED = "textured"
LISTENING_TEXTURED_RST_TONE = 5
KOCH_CHALLENGE_START_SESSION = 9
KOCH_CHALLENGE_END_SESSION = 12
KOCH_PROBE_PHASE_CHALLENGE = "challenge-block"
KOCH_PROGRESSION_ROLE_SUPPORTING_GEAR_UP = "supporting_gear_up"


def listening_condition_for_session(set_session: int) -> str:
    if set_session % 2 == 1:
        return LISTENING_CONDITION_DEFAULT
    return LISTENING_CONDITION_TEXTURED


def audio_params_for_listening_condition(
    params: AudioParameters,
    condition: str,
) -> AudioParameters:
    if condition == LISTENING_CONDITION_TEXTURED:
        return replace(
            params,
            envelope_ramp_seconds=max(
                params.envelope_ramp_seconds,
                texture.envelope_seconds_for_rst_tone(LISTENING_TEXTURED_RST_TONE),
            ),
            tone_distortion=max(
                params.tone_distortion,
                texture.distortion_for_rst_tone(LISTENING_TEXTURED_RST_TONE),
            ),
            tone_ripple=max(
                params.tone_ripple,
                texture.ripple_for_rst_tone(LISTENING_TEXTURED_RST_TONE),
            ),
        )
    return params


def rst_fields_for_audio_params(params: AudioParameters) -> dict[str, int]:
    return {
        "s": texture.rst_strength_for_bed_level(params.receiver_bed),
        "t": texture.rst_tone_for_envelope_seconds(params.envelope_ramp_seconds),
    }


def is_koch_challenge_session(set_session: int) -> bool:
    return KOCH_CHALLENGE_START_SESSION <= set_session <= KOCH_CHALLENGE_END_SESSION
