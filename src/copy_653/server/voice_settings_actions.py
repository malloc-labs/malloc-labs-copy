"""WebSocket actions for reading and writing the ``[voice]`` config table.

Mirrors the shape of :mod:`copy_653.server.audio_settings_actions`:

* ``get-voice-settings`` returns the current persisted settings.
* ``set-voice-settings`` persists new values via
  :func:`copy_653.config.save_voice_settings` and echoes the result
  back. ``model_path`` is intentionally nullable — passing ``null``
  (or an empty string) clears the field, which deletes the key from
  ``config.toml`` while leaving the rest of the ``[voice]`` table
  intact.

Both actions resolve the absolute model path and check whether it
exists on disk so the settings UI can re-render the Status section
without a separate HTTP call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from websockets.server import WebSocketServerProtocol

from copy_653.config import VoiceSettings, load_voice_settings, save_voice_settings
from copy_653.server.wire_events import _send_event


async def _get_voice_settings_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
) -> None:
    await _send_event(ws, _voice_settings_event(load_voice_settings(config_path)))


async def _set_voice_settings_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
    config_path: Path,
) -> None:
    try:
        language = _required_language(message.get("language"))
        model_path = _nullable_model_path(message.get("model_path"))
        settings = save_voice_settings(
            language=language,
            model_path=model_path,
            path=config_path,
        )
    except ValueError as err:
        await _send_event(
            ws,
            {"type": "error", "reason": "invalid-voice-settings", "detail": str(err)},
        )
        return

    await _send_event(ws, _voice_settings_event(settings))


def _voice_settings_event(settings: VoiceSettings) -> dict[str, Any]:
    resolved = settings.resolved_model_path()
    return {
        "type": "voice-settings",
        "language": settings.language,
        "model_path": settings.model_path,
        "model_path_resolved": str(resolved) if resolved is not None else None,
        "model_exists": bool(resolved and Path(resolved).is_dir()),
    }


def _required_language(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("language must be a non-empty string")
    return value.strip()


def _nullable_model_path(value: Any) -> str | None:
    """Accept ``None``, ``""``, or a non-empty string. Empty string clears."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("model_path must be a string or null")
    stripped = value.strip()
    return stripped or None
