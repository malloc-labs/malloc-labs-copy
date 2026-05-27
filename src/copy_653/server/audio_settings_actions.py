"""Audio and settings WebSocket actions for the Copy web server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from websockets.server import WebSocketServerProtocol

from copy_653.audio import texture
from copy_653.config import (
    load_audio_parameters,
    load_developer_settings,
    load_keyer_settings,
    load_recognition_settings,
    load_save_directory,
    load_warm_up_timeout_seconds,
    save_audio_timing,
    save_developer_settings,
    save_keyer_settings,
    save_recognition_settings,
    save_save_directory,
    save_warm_up_timeout_seconds,
)
from copy_653.server.validation import (
    _optional_bool,
    _optional_bounded_int,
    _optional_non_empty_string,
    _optional_positive_int,
    _strict_positive_int,
)
from copy_653.server.wire_events import (
    _audio_settings_event_from_params,
    _send_event,
)


async def _get_audio_settings_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
) -> None:
    params = load_audio_parameters(config_path)
    keyer_settings = load_keyer_settings(config_path)
    developer_settings = load_developer_settings(config_path)
    save_directory = load_save_directory(config_path)
    warm_up_timeout = load_warm_up_timeout_seconds(config_path)
    recognition_settings = load_recognition_settings(config_path)
    await _send_event(
        ws,
        _audio_settings_event_from_params(
            params,
            keyer_settings,
            developer_settings,
            save_directory,
            warm_up_timeout_seconds=warm_up_timeout,
            recognition_settings=recognition_settings,
        ),
    )


async def _set_audio_settings_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
    config_path: Path,
) -> None:
    try:
        character_wpm = _strict_positive_int(message.get("character_wpm"), "character_wpm")
        effective_wpm = _strict_positive_int(message.get("effective_wpm"), "effective_wpm")
        tone_shape = _optional_bounded_int(
            message.get("tone_shape"),
            "tone_shape",
            texture.MIN_TONE_SHAPE,
            texture.MAX_TONE_SHAPE,
        )
        receiver_bed = _optional_bounded_int(
            message.get("receiver_bed"),
            "receiver_bed",
            texture.MIN_RECEIVER_BED,
            texture.MAX_RECEIVER_BED,
        )
        cadence_variation = _optional_bounded_int(
            message.get("cadence_variation"),
            "cadence_variation",
            texture.MIN_CADENCE_VARIATION,
            texture.MAX_CADENCE_VARIATION,
        )
        keyer_mode = _optional_non_empty_string(
            message.get("keyer_mode"),
            "keyer_mode",
        )
        hh_clear_enabled = _optional_bool(
            message.get("hh_clear_enabled"),
            "hh_clear_enabled",
        )
        save_directory_input = _optional_non_empty_string(
            message.get("save_directory"),
            "save_directory",
        )
        params = save_audio_timing(
            character_speed_wpm=character_wpm,
            effective_speed_wpm=effective_wpm,
            tone_shape=tone_shape,
            receiver_bed=receiver_bed,
            cadence_variation=cadence_variation,
            path=config_path,
        )
        if keyer_mode is not None:
            keyer_settings = save_keyer_settings(
                keyer_mode=keyer_mode,
                path=config_path,
            )
        else:
            keyer_settings = load_keyer_settings(config_path)
        if hh_clear_enabled is not None:
            developer_settings = save_developer_settings(
                hh_clear_enabled=hh_clear_enabled,
                path=config_path,
            )
        else:
            developer_settings = load_developer_settings(config_path)
        if save_directory_input is not None:
            save_directory = save_save_directory(save_directory_input, path=config_path)
        else:
            save_directory = load_save_directory(config_path)
        raw_warm_up = message.get("warm_up_timeout_minutes")
        if raw_warm_up is not None:
            if not isinstance(raw_warm_up, (int, float)) or isinstance(raw_warm_up, bool):
                raise ValueError("warm_up_timeout_minutes must be a number")
            warm_up_timeout = save_warm_up_timeout_seconds(
                float(raw_warm_up) * 60, path=config_path
            )
        else:
            warm_up_timeout = load_warm_up_timeout_seconds(config_path)

        raw_say_before = _optional_bool(message.get("say_before"), "say_before")
        raw_morse_count = _optional_positive_int(message.get("morse_count"), "morse_count")
        raw_recognition_time = _optional_bounded_int(
            message.get("recognition_time_ms"), "recognition_time_ms", 0, 60000
        )
        raw_say_after = _optional_bool(message.get("say_after"), "say_after")
        has_recognition = any(
            v is not None
            for v in [raw_say_before, raw_morse_count, raw_recognition_time, raw_say_after]
        )
        if has_recognition:
            current_recognition = load_recognition_settings(config_path)
            recognition_settings = save_recognition_settings(
                say_before=(
                    raw_say_before if raw_say_before is not None else current_recognition.say_before
                ),
                morse_count=(
                    raw_morse_count
                    if raw_morse_count is not None
                    else current_recognition.morse_count
                ),
                recognition_time_ms=(
                    raw_recognition_time
                    if raw_recognition_time is not None
                    else current_recognition.recognition_time_ms
                ),
                say_after=(
                    raw_say_after if raw_say_after is not None else current_recognition.say_after
                ),
                path=config_path,
            )
        else:
            recognition_settings = load_recognition_settings(config_path)
    except ValueError as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "invalid-audio-settings",
                "detail": str(exc),
            },
        )
        return

    await _send_event(
        ws,
        _audio_settings_event_from_params(
            params,
            keyer_settings,
            developer_settings,
            save_directory,
            warm_up_timeout_seconds=warm_up_timeout,
            recognition_settings=recognition_settings,
        ),
    )
