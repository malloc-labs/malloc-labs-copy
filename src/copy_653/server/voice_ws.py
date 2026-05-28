"""WebSocket handler for ``/voice/ws`` — binary PCM in, JSON events out.

A separate WS path from the main ``/`` handler so binary audio frames
do not pollute the JSON action protocol in
:mod:`copy_653.server.connection`. Each connection gets its own
:class:`copy_653.voice.Recognizer`; the model is loaded per connection
to keep this module's lifecycle independent of the engine's main
connection state. For typical use (one browser tab opening voice
briefly during answer entry) the ~50 MB load is amortised across the
session and acceptable.

Wire protocol (over a single WS at ``/voice/ws``)
=================================================

Client → server:

* Binary frames — Int16 little-endian PCM, mono, 16 kHz. Frame size
  is the worklet's quantum (typically 128 samples).
* Text frame ``"reset"`` — flush in-flight decoder state without
  rebuilding the model.

Server → client (JSON text frames, one per event):

* On connect, if voice is misconfigured::

    {"type": "error", "reason": "voice-unavailable", "message": "<detail>"}

  …followed by close. The client is expected to render the message
  verbatim — the engine names exactly what went wrong (per spec §1.5).

* During recognition::

    {"type": "partial", "text": "alp", "symbol": null}
    {"type": "final",   "text": "alpha", "symbol": "A"}

  ``symbol`` is ``null`` for ``[unk]`` and for any phrase that
  somehow isn't in the lexicon (shouldn't happen given the grammar
  constraint, but the recogniser callback is defensive).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol

from copy_653.config import DEFAULT_CONFIG_PATH, load_voice_settings
from copy_653.voice import (
    FinalResult,
    PartialResult,
    Recognizer,
    VoiceUnavailableError,
)

logger = logging.getLogger(__name__)


async def voice_handler(
    ws: WebSocketServerProtocol,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    recognizer_factory: Any = None,
) -> None:
    """Handle one ``/voice/ws`` connection.

    ``recognizer_factory`` is for tests: a callable
    ``(VoiceSettings) -> Recognizer``. Defaults to
    :meth:`Recognizer.from_settings`.
    """
    settings = load_voice_settings(config_path)
    factory = recognizer_factory or Recognizer.from_settings

    try:
        recognizer = factory(settings)
    except VoiceUnavailableError as err:
        await _send_error(ws, "voice-unavailable", str(err))
        await ws.close()
        return

    logger.info("voice ws connected from %s", ws.remote_address)
    try:
        async for message in ws:
            if isinstance(message, bytes):
                for event in recognizer.feed_pcm(message):
                    await _send_event(ws, event)
            elif isinstance(message, str) and message == "reset":
                recognizer.reset()
    except ConnectionClosed:
        pass
    finally:
        logger.info("voice ws closed")


async def _send_event(ws: WebSocketServerProtocol, event: PartialResult | FinalResult) -> None:
    if isinstance(event, FinalResult):
        await ws.send(_json({"type": "final", "text": event.text, "symbol": event.symbol}))
    else:
        await ws.send(_json({"type": "partial", "text": event.text, "symbol": event.symbol}))


async def _send_error(ws: WebSocketServerProtocol, reason: str, message: str) -> None:
    await ws.send(_json({"type": "error", "reason": reason, "message": message}))


def _json(payload: dict[str, Any]) -> str:
    # Local import keeps the hot path's import surface tiny.
    import json

    return json.dumps(payload, ensure_ascii=False)
