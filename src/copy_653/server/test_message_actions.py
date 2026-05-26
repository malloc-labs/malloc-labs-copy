"""WebSocket actions for Marconi test-message playback and WAV export."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from websockets.server import WebSocketServerProtocol

from copy_653.audio import playback
from copy_653.audio.wav import encode_pcm16_wav
from copy_653.server.test_message_audio import build_marconi_test_message
from copy_653.server.validation import _audio_params_from_settings_message
from copy_653.server.wire_events import _send_event

# Divisible by 3 so every non-final base64 chunk can be concatenated safely.
WAV_EXPORT_CHUNK_SIZE = 245_760


async def _play_test_message_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
) -> None:
    try:
        params = _audio_params_from_settings_message(message)
    except ValueError as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "invalid-test-message-settings",
                "detail": str(exc),
            },
        )
        return

    await _send_event(ws, {"type": "test-message-start"})
    try:
        await asyncio.to_thread(playback.play, build_marconi_test_message(params), params)
    except asyncio.CancelledError:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        raise
    except Exception as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "test-message-playback-failed",
                "detail": str(exc),
            },
        )
        raise
    await _send_event(ws, {"type": "test-message-end"})


async def _save_test_message_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
) -> None:
    try:
        params = _audio_params_from_settings_message(message)
        wav_bytes = await asyncio.to_thread(
            lambda: encode_pcm16_wav(build_marconi_test_message(params), params.sample_rate_hz)
        )
    except ValueError as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "invalid-test-message-settings",
                "detail": str(exc),
            },
        )
        return

    filename = "copy-653-marconi-test-message.wav"
    await _send_event(
        ws,
        {
            "type": "test-message-wav-start",
            "filename": filename,
            "byte_length": len(wav_bytes),
        },
    )
    for start in range(0, len(wav_bytes), WAV_EXPORT_CHUNK_SIZE):
        encoded = base64.b64encode(wav_bytes[start : start + WAV_EXPORT_CHUNK_SIZE]).decode("ascii")
        await _send_event(ws, {"type": "test-message-wav-chunk", "data": encoded})
    await _send_event(ws, {"type": "test-message-wav-end", "filename": filename})
