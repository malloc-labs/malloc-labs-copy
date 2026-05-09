"""Localhost HTTP + WebSocket surface for the engine.

This is the engine ↔ UI touch point (spec §1.4). One asyncio loop, one
TCP port, two protocols multiplexed by the ``websockets`` library:

- Plain HTTP serves the static UI (``web/index.html``, ``web/css/*``,
  ``web/js/*``). The ``process_request`` hook intercepts non-WS
  requests and answers them as HTTP responses.
- WebSocket upgrades hit :func:`handler`, which reads JSON commands
  from the client and pushes JSON events back. The schema is small
  and lives in this module's docstring (see "Wire protocol" below).

For the v0 desktop shape (spec §1.3 row 1) the server binds
``127.0.0.1`` only — the engine and UI run on the same machine. Future
Pi / standalone shapes will need a configurable bind host; that is not
v0.

Port selection follows the honesty contract (spec §1.5): we probe
upward from the requested port and fail loudly if nothing in the
search window is free, rather than silently picking an arbitrary port
the learner cannot predict.

Wire protocol (v0)
==================

Client → server, JSON over WS::

    {"action": "play", "symbols": "KMK"}

Server → client, JSON over WS, one frame per event::

    {"type": "session-start", "symbols": "KMK"}
    {"type": "symbol", "symbol": "K", "t_on": 0.0,    "t_off": 0.18}
    {"type": "symbol", "symbol": "M", "t_on": 0.42,   "t_off": 0.6}
    {"type": "symbol", "symbol": "K", "t_on": 0.84,   "t_off": 1.02}
    {"type": "session-end"}

The ``t_on`` / ``t_off`` values are the engine's intended schedule (see
:func:`copy_653.audio.synth.compute_timeline`). They are not
re-measured against the audio device's actual output. This is
deliberate: the truth recorded in a session is what was sent, not what
a wall clock observed.

This is a development-grade pipe. ``play`` is a placeholder action
that exists so the engine ↔ UI seam can be exercised end-to-end before
:mod:`copy_653.session` lands and replaces the hard-coded symbol list
with a generated stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import socket
from http import HTTPStatus
from pathlib import Path
from typing import Any

from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol, serve

from copy_653.audio import playback, synth
from copy_653.audio.parameters import AudioParameters
from copy_653.config import load_audio_parameters

DEFAULT_PORT = 8653
DEFAULT_PORT_SEARCH_SPAN = 20

logger = logging.getLogger(__name__)


def find_web_root() -> Path:
    """Locate the ``web/`` directory by walking up from this file.

    Works for editable installs (``pip install -e .``), which is the v0
    distribution shape (spec §11.1). A future packaged install would
    need ``importlib.resources`` and a ``web/`` bundled into the
    package; that is not v0.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "web"
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate
    raise RuntimeError(
        f"Could not locate web/ relative to {here}. "
        "v0 expects an editable install layout (spec §11.1)."
    )


def find_available_port(start: int, span: int = DEFAULT_PORT_SEARCH_SPAN) -> int:
    """Return the first free TCP port in ``[start, start + span)`` on 127.0.0.1.

    Raises :class:`RuntimeError` if every candidate is occupied — per
    spec §1.5 we do not silently pick something the learner cannot
    predict. There is a small TOCTOU window between this probe and the
    actual ``serve()`` bind; for localhost dev that is acceptable.
    """
    if span <= 0:
        raise ValueError(f"span must be positive, got {span}")

    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port

    raise RuntimeError(
        f"No port available in [{start}, {start + span}). "
        "Pass --port to choose a different starting point."
    )


def _build_static_handler(web_root: Path):
    """Return a ``process_request`` callable bound to ``web_root``.

    The callable is what websockets invokes for every incoming HTTP
    request before deciding whether to upgrade to WS. Returning
    ``None`` lets the WS handshake proceed; returning a 3-tuple
    answers the request as plain HTTP.
    """

    async def process_request(
        path: str, request_headers: Headers
    ) -> tuple[HTTPStatus, list[tuple[str, str]], bytes] | None:
        # Strip the query string for static lookups; we do not use it
        # for anything in v0.
        clean_path = path.split("?", 1)[0]

        # /ws is the only WS endpoint. Returning None hands control
        # back to websockets to complete the upgrade.
        if clean_path == "/ws":
            return None

        target = "index.html" if clean_path == "/" else clean_path.lstrip("/")
        resolved = (web_root / target).resolve()

        # Defence in depth against path traversal — a request like
        # /../etc/passwd should 404, not escape the web root.
        try:
            resolved.relative_to(web_root)
        except ValueError:
            return _http_response(HTTPStatus.NOT_FOUND, b"not found")

        if not resolved.is_file():
            return _http_response(HTTPStatus.NOT_FOUND, b"not found")

        body = resolved.read_bytes()
        mime, _ = mimetypes.guess_type(resolved.name)
        content_type = mime or "application/octet-stream"
        # Modern browsers want charset=utf-8 on text payloads — without
        # it Firefox in particular complains about the meta charset.
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type = f"{content_type}; charset=utf-8"

        return (
            HTTPStatus.OK,
            [
                ("Content-Type", content_type),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ],
            body,
        )

    return process_request


def _http_response(
    status: HTTPStatus, body: bytes
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    return (
        status,
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
        body,
    )


async def _send_event(ws: WebSocketServerProtocol, event: dict[str, Any]) -> None:
    """Serialise ``event`` to JSON and send it on ``ws``.

    Swallows :class:`ConnectionClosed` because a learner closing the
    tab mid-session is normal, not an error. Other exceptions
    propagate per spec §1.5.
    """
    try:
        await ws.send(json.dumps(event))
    except ConnectionClosed:
        pass


async def _play_action(ws: WebSocketServerProtocol, symbols: str, params: AudioParameters) -> None:
    """Synthesise ``symbols``, play in a worker thread, push timeline events.

    The audio plays on a worker thread (sounddevice is blocking by
    contract, see :mod:`copy_653.audio.playback`), while the asyncio
    loop sleeps between symbol boundaries to push live events. The two
    schedules drift independently; the events are display-grade, the
    audio is the truth.
    """
    symbol_list = list(symbols)
    timeline = synth.compute_timeline(symbol_list, params)

    await _send_event(ws, {"type": "session-start", "symbols": symbols})

    samples = synth.synthesize_sequence(symbol_list, params)
    audio_task = asyncio.create_task(asyncio.to_thread(playback.play, samples, params))

    cursor = 0.0
    for symbol, t_on, t_off in timeline:
        wait = t_on - cursor
        if wait > 0:
            await asyncio.sleep(wait)
        cursor = t_on
        await _send_event(
            ws,
            {"type": "symbol", "symbol": symbol, "t_on": t_on, "t_off": t_off},
        )

    # Wait for the audio thread to actually finish before declaring the
    # session ended — premature end-of-session would lie about what the
    # learner is hearing (§1.5).
    await audio_task
    await _send_event(ws, {"type": "session-end"})


async def handler(ws: WebSocketServerProtocol, params: AudioParameters | None = None) -> None:
    """Top-level WS connection handler. Dispatches incoming JSON commands."""
    audio_params = params if params is not None else load_audio_parameters()
    try:
        async for raw in ws:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await _send_event(ws, {"type": "error", "reason": "invalid-json"})
                continue

            action = message.get("action")
            if action == "play":
                symbols = message.get("symbols", "")
                if not isinstance(symbols, str):
                    await _send_event(ws, {"type": "error", "reason": "symbols-must-be-string"})
                    continue
                try:
                    await _play_action(ws, symbols, audio_params)
                except KeyError as exc:
                    # patterns.pattern_for raises KeyError for unknown
                    # symbols — surface plainly rather than silently
                    # skipping (spec §1.5).
                    await _send_event(
                        ws, {"type": "error", "reason": "unknown-symbol", "symbol": str(exc)}
                    )
            else:
                await _send_event(ws, {"type": "error", "reason": "unknown-action"})
    except ConnectionClosed:
        pass


async def serve_app(
    port: int = DEFAULT_PORT,
    port_search_span: int = DEFAULT_PORT_SEARCH_SPAN,
    web_root: Path | None = None,
    params: AudioParameters | None = None,
) -> tuple[Any, int]:
    """Start the server and return ``(server, bound_port)``.

    The caller is responsible for keeping the event loop alive (e.g.
    ``await server.wait_closed()``). Useful for tests that want to
    drive the server programmatically.
    """
    chosen_port = find_available_port(port, port_search_span)
    resolved_web_root = web_root if web_root is not None else find_web_root()
    audio_params = params if params is not None else load_audio_parameters()

    process_request = _build_static_handler(resolved_web_root)

    async def _connection(ws: WebSocketServerProtocol) -> None:
        await handler(ws, params=audio_params)

    server = await serve(
        _connection,
        "127.0.0.1",
        chosen_port,
        process_request=process_request,
    )
    return server, chosen_port


async def run(port: int = DEFAULT_PORT, port_search_span: int = DEFAULT_PORT_SEARCH_SPAN) -> None:
    """Run the server forever. Entry point for ``python -m copy_653``."""
    server, bound_port = await serve_app(port=port, port_search_span=port_search_span)
    if bound_port != port:
        logger.info("requested port %d was in use; bound %d instead", port, bound_port)
    print(f"Copy engine listening on http://127.0.0.1:{bound_port}")
    await server.wait_closed()
