"""Audio and settings WebSocket actions for the Copy web server."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from websockets.server import WebSocketServerProtocol

from copy_653.audio import texture
from copy_653.audio import synth
from copy_653.config import (
    load_audio_parameters,
    load_developer_settings,
    load_keyer_settings,
    load_recognition_settings,
    load_save_directory,
    load_warm_up_timeout_seconds,
    save_audio_timing,
    save_audio_output_device,
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


def _coerce_output_device(value: Any) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("output_device must be a device name, index, or null")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    raise ValueError("output_device must be a device name, index, or null")


def _audio_output_devices_event(config_path: Path) -> dict[str, Any]:
    params = load_audio_parameters(config_path)
    devices: list[dict[str, Any]] = []
    default_output_device: int | None = None
    try:
        import sounddevice as sd

        default_pair = getattr(sd.default, "device", None)
        if isinstance(default_pair, (list, tuple)) and len(default_pair) >= 2:
            default_output_device = default_pair[1] if isinstance(default_pair[1], int) else None
        raw_devices = sd.query_devices()
        for idx, info in enumerate(raw_devices):
            if int(info.get("max_output_channels", 0)) <= 0:
                continue
            hostapi_name = ""
            try:
                hostapi_name = str(sd.query_hostapis(info["hostapi"]).get("name", ""))
            except Exception:
                hostapi_name = ""
            name = str(info.get("name", f"Device {idx}"))
            full_name = f"{name}, {hostapi_name}" if hostapi_name else name
            devices.append(
                {
                    "index": int(info.get("index", idx)),
                    "name": name,
                    "hostapi": hostapi_name,
                    "full_name": full_name,
                    "max_output_channels": int(info.get("max_output_channels", 0)),
                    "default_samplerate": float(info.get("default_samplerate", 0.0)),
                    "is_default_output": default_output_device == int(info.get("index", idx)),
                }
            )
    except Exception as exc:
        return {
            "type": "audio-output-devices",
            "current_output_device": params.output_device,
            "default_output_device": default_output_device,
            "devices": [],
            "error": str(exc),
        }

    return {
        "type": "audio-output-devices",
        "current_output_device": params.output_device,
        "default_output_device": default_output_device,
        "devices": devices,
    }


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


async def _get_audio_output_devices_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
) -> None:
    await _send_event(ws, _audio_output_devices_event(config_path))


async def _set_audio_output_device_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
    config_path: Path,
) -> None:
    try:
        output_device = _coerce_output_device(message.get("output_device"))
        save_audio_output_device(output_device, path=config_path)
    except ValueError as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "invalid-audio-output-device",
                "detail": str(exc),
            },
        )
        return
    await _send_event(ws, _audio_output_devices_event(config_path))


async def _play_audio_output_test_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
    config_path: Path,
) -> None:
    try:
        output_device = _coerce_output_device(message.get("output_device"))
        params = load_audio_parameters(config_path)
        samples = synth.synthesize_sequence(["K"], params)
        import sounddevice as sd

        await _send_event(ws, {"type": "audio-output-test-start", "output_device": output_device})
        await asyncio.to_thread(
            sd.play,
            samples,
            samplerate=params.sample_rate_hz,
            device=output_device,
            blocking=True,
        )
    except Exception as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "audio-output-test-failed",
                "detail": str(exc),
            },
        )
        return
    await _send_event(ws, {"type": "audio-output-test-end", "output_device": output_device})


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
