"""Letter and Morse-preview WebSocket actions for the Copy web server."""

from __future__ import annotations

import asyncio
from pathlib import Path

from websockets.server import WebSocketServerProtocol

from copy_653.config import load_audio_parameters, load_letters_config
from copy_653.letters import play_letter_sequence, play_morse_sequence
from copy_653.server.wire_events import _send_event


async def _run_morse_repeat(
    ws: WebSocketServerProtocol,
    symbol: str,
    repeats: int,
    config_path: Path,
) -> None:
    """Play bare Morse for ``symbol`` ``repeats`` times. Emits start/end frames.

    Used by the Cadence page's Alt+character preview keybind. Reads
    audio params fresh so a learner who edits WPM mid-session hears the
    change on the next preview.
    """
    audio_params = load_audio_parameters(config_path)

    await _send_event(ws, {"type": "morse-repeat-start", "symbol": symbol, "repeats": repeats})
    try:
        await play_morse_sequence(symbol, audio_params, repeats=repeats)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "morse-repeat-failed",
                "symbol": symbol,
                "detail": str(exc),
            },
        )
        raise
    await _send_event(ws, {"type": "morse-repeat-end", "symbol": symbol})


async def _run_letter_sequence(
    ws: WebSocketServerProtocol,
    symbol: str,
    config_path: Path,
    anchors_dir: Path,
) -> None:
    """Send ``letter-start``, play the sequence, send ``letter-end``.

    Reads audio and letters config fresh per call (per the project's
    no-caching contract — the learner's hand-edited config takes
    effect immediately). Any exception during playback surfaces as an
    ``error`` event then re-raises so the caller's task records it.

    On :class:`asyncio.CancelledError` (a new ``play-letter`` arrived),
    no terminal event is sent — the new sequence's ``letter-start`` is
    the authoritative new state.
    """
    audio_params = load_audio_parameters(config_path)
    letters_config = load_letters_config(config_path)

    await _send_event(ws, {"type": "letter-start", "symbol": symbol})
    try:
        await play_letter_sequence(symbol, audio_params, letters_config, anchors_dir)
    except asyncio.CancelledError:
        # Superseded by another play-letter; the new task already sent
        # its own letter-start.
        raise
    except Exception as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "letter-playback-failed",
                "symbol": symbol,
                "detail": str(exc),
            },
        )
        raise
    await _send_event(ws, {"type": "letter-end", "symbol": symbol})
