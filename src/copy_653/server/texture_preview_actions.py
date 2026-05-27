"""WebSocket actions for looping texture-preview playback and WAV export."""

from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path
from typing import Any

from websockets.server import WebSocketServerProtocol

from copy_653.audio import playback
from copy_653.audio.wav import encode_pcm16_wav
from copy_653.config import load_claimed_symbols
from copy_653.server.texture_preview_audio import build_texture_preview
from copy_653.server.validation import _audio_params_from_settings_message
from copy_653.server.wire_events import _send_event

WAV_EXPORT_CHUNK_SIZE = 245_760


async def _play_texture_preview_loop(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
    config_path: Path,
) -> None:
    """Synthesise and play texture preview chunks in a loop until cancelled."""
    try:
        params = _audio_params_from_settings_message(message)
    except ValueError as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "invalid-texture-preview-settings",
                "detail": str(exc),
            },
        )
        return

    claimed = load_claimed_symbols(config_path)
    if not claimed:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "texture-preview-no-symbols",
                "detail": "No claimed symbols — claim at least one symbol first.",
            },
        )
        return

    await _send_event(ws, {"type": "texture-preview-start"})
    try:
        seed = int(time.monotonic() * 1000)
        while True:
            samples = await asyncio.to_thread(build_texture_preview, params, claimed, seed=seed)
            await asyncio.to_thread(playback.play, samples, params)
            seed += 1
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
                "reason": "texture-preview-playback-failed",
                "detail": str(exc),
            },
        )
        raise
    finally:
        await _send_event(ws, {"type": "texture-preview-end"})


async def _save_texture_preview_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
    config_path: Path,
) -> None:
    """Synthesise one texture preview chunk and send it as a WAV download."""
    try:
        params = _audio_params_from_settings_message(message)
    except ValueError as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "invalid-texture-preview-settings",
                "detail": str(exc),
            },
        )
        return

    claimed = load_claimed_symbols(config_path)
    if not claimed:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "texture-preview-no-symbols",
                "detail": "No claimed symbols — claim at least one symbol first.",
            },
        )
        return

    seed = int(time.monotonic() * 1000)
    try:
        wav_bytes = await asyncio.to_thread(
            lambda: encode_pcm16_wav(
                build_texture_preview(params, claimed, seed=seed),
                params.sample_rate_hz,
            )
        )
    except Exception as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "texture-preview-playback-failed",
                "detail": str(exc),
            },
        )
        return

    filename = "copy-653-texture-preview.wav"
    await _send_event(
        ws,
        {
            "type": "texture-preview-wav-start",
            "filename": filename,
            "byte_length": len(wav_bytes),
        },
    )
    for start in range(0, len(wav_bytes), WAV_EXPORT_CHUNK_SIZE):
        encoded = base64.b64encode(wav_bytes[start : start + WAV_EXPORT_CHUNK_SIZE]).decode("ascii")
        await _send_event(ws, {"type": "texture-preview-wav-chunk", "data": encoded})
    await _send_event(ws, {"type": "texture-preview-wav-end", "filename": filename})
