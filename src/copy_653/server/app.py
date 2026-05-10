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

    {"action": "start"}
    {"action": "stop"}
    {"action": "claim-symbol", "symbol": "U"}
    {"action": "play-letter", "symbol": "K"}

Server → client, JSON over WS, one frame per event. Pushed
unsolicited on connect, and after every change::

    {"type": "claimed-symbols", "symbols": ["K", "M"], "suggested_next": "U"}

During a session::

    {"type": "session-start", "symbols": ["K","M","K"], "duration_seconds": 30, "seed": 12345}
    {"type": "symbol", "symbol": "K", "t_on": 0.0,  "t_off": 0.18}
    {"type": "symbol", "symbol": "M", "t_on": 0.42, "t_off": 0.6}
    {"type": "session-end"}

During a Letters playback (Koch hub → Letters page)::

    {"type": "letter-start", "symbol": "K"}
    {"type": "letter-end",   "symbol": "K"}

``stop`` cancels an in-flight session. The engine cancels the audio
task and sends ``session-end`` before closing the session. If no
session is in flight, ``stop`` is a no-op.

A second ``play-letter`` while a sequence is playing supersedes the
first: the in-flight task is cancelled and the new one starts.
``letter-end`` is only sent on natural completion; a superseded run
emits no terminal event because the next ``letter-start`` is the
authoritative new state.

The ``t_on`` / ``t_off`` values are the engine's intended schedule (see
:func:`copy_653.audio.synth.compute_timeline`). They are not
re-measured against the audio device's actual output. This is
deliberate: the truth recorded in a session is what was sent, not what
a wall clock observed.

The ``seed`` carried on ``session-start`` is the value
:mod:`copy_653.sequence.generator` used to draw this stream — recorded
so the same stream can be replayed later (spec §2.8).

The configuration (claimed symbols, session duration) is read from
disk per request rather than cached at server boot. A learner who
hand-edits ``config.toml`` mid-session sees their change on the next
``start``. This costs one TOML parse per action and keeps the engine
honest about what is actually configured.

This is a development-grade pipe. ``start`` carries no mode dispatch
yet; that arrives with :mod:`copy_653.session`. The wire protocol
above is the seam ``session`` will widen — same shape, more fields.
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

from copy_653 import sequence
from copy_653.audio import patterns, playback, synth
from copy_653.config import (
    DEFAULT_CONFIG_PATH,
    load_audio_parameters,
    load_claimed_symbols,
    load_letters_config,
    load_session_duration,
    save_claimed_symbols,
)
from copy_653.letters import (
    NATO_PHONETIC_NAMES,
    find_anchors_dir,
    play_letter_sequence,
)

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


def _claimed_symbols_event(claimed: tuple[str, ...]) -> dict[str, Any]:
    """Build the ``claimed-symbols`` event payload from a claimed list."""
    return {
        "type": "claimed-symbols",
        "symbols": list(claimed),
        "suggested_next": patterns.next_koch_after(claimed),
    }


async def _start_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
) -> None:
    """Generate a stream from the claimed set, play it, push timeline events.

    Reads the claimed symbol set, audio parameters, and session
    duration fresh from the config file — a learner who edited
    ``config.toml`` between actions sees the new values immediately.
    """
    audio_params = load_audio_parameters(config_path)
    claimed = load_claimed_symbols(config_path)
    duration = load_session_duration(config_path)

    if not claimed:
        # The default is KOCH_FIRST_PAIR; an empty claimed set means
        # the learner has actively cleared their config. Honest refusal
        # rather than synthesising silence (spec §1.5).
        await _send_event(ws, {"type": "error", "reason": "no-claimed-symbols"})
        return

    generated = sequence.generate(
        claimed_set=claimed,
        duration_seconds=duration,
        params=audio_params,
    )

    if not generated.symbols:
        # Duration too short for any single claimed symbol.
        await _send_event(
            ws,
            {"type": "error", "reason": "duration-too-short", "duration_seconds": duration},
        )
        return

    symbols_list = list(generated.symbols)
    timeline = synth.compute_timeline(symbols_list, audio_params)

    await _send_event(
        ws,
        {
            "type": "session-start",
            "symbols": symbols_list,
            "duration_seconds": duration,
            "seed": generated.seed,
        },
    )

    samples = synth.synthesize_sequence(symbols_list, audio_params)
    audio_task = asyncio.create_task(asyncio.to_thread(playback.play, samples, audio_params))

    try:
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

    except asyncio.CancelledError:
        # Stop was requested. Signal PortAudio to abort the current stream
        # immediately — sd.stop() is the only way to interrupt a blocking
        # sd.play() running in a thread (asyncio task cancellation alone
        # does not reach into the thread).
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass  # No audio device or sounddevice not installed — ignore
        audio_task.cancel()
        raise  # Re-raise so _run_session's handler sends session-end


async def _claim_symbol_action(
    ws: WebSocketServerProtocol,
    symbol: str,
    config_path: Path,
) -> None:
    """Append ``symbol`` to the claimed set and broadcast the new state.

    Idempotent: claiming a symbol already in the set is a no-op (still
    rebroadcasts, so a UI out of sync converges).

    Validation per spec §1.5: an unknown symbol surfaces as an
    ``error`` event without mutating the config.
    """
    if not isinstance(symbol, str) or len(symbol) != 1:
        await _send_event(ws, {"type": "error", "reason": "symbol-must-be-single-character"})
        return

    upper = symbol.upper()
    try:
        patterns.pattern_for(upper)
    except KeyError:
        await _send_event(ws, {"type": "error", "reason": "unknown-symbol", "symbol": upper})
        return

    claimed = load_claimed_symbols(config_path)
    if upper not in claimed:
        new_claimed = (*claimed, upper)
        save_claimed_symbols(new_claimed, config_path)
        claimed = new_claimed

    await _send_event(ws, _claimed_symbols_event(claimed))


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


async def handler(
    ws: WebSocketServerProtocol,
    config_path: Path = DEFAULT_CONFIG_PATH,
    anchors_dir: Path | None = None,
) -> None:
    """Top-level WS connection handler. Dispatches incoming JSON commands."""
    if anchors_dir is None:
        anchors_dir = find_anchors_dir()

    # Per-connection state: in-flight session task and letter task.
    # A stop action cancels the session task; a new play-letter cancels
    # and replaces the letter task.
    current_session_task: asyncio.Task[None] | None = None
    current_letter_task: asyncio.Task[None] | None = None

    # Push current state on connect so the UI does not need to ask.
    claimed = load_claimed_symbols(config_path)
    await _send_event(ws, _claimed_symbols_event(claimed))

    try:
        async for raw in ws:
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await _send_event(ws, {"type": "error", "reason": "invalid-json"})
                continue

            action = message.get("action")
            if action == "start":
                # Cancel any in-flight session before starting a new one.
                if current_session_task is not None and not current_session_task.done():
                    current_session_task.cancel()
                    try:
                        await current_session_task
                    except (asyncio.CancelledError, Exception):
                        pass

                async def _run_session() -> None:
                    try:
                        await _start_action(ws, config_path)
                    except ValueError as exc:
                        await _send_event(
                            ws,
                            {"type": "error", "reason": "invalid-config", "detail": str(exc)},
                        )
                    except asyncio.CancelledError:
                        # Stop was requested — send session-end so the UI
                        # knows the session is over (spec §1.5).
                        await _send_event(ws, {"type": "session-end"})

                current_session_task = asyncio.create_task(_run_session())
            elif action == "stop":
                # Cancel the in-flight session if one is running.
                # session-end is sent by _run_session's CancelledError handler.
                if current_session_task is not None and not current_session_task.done():
                    current_session_task.cancel()
            elif action == "claim-symbol":
                await _claim_symbol_action(ws, message.get("symbol", ""), config_path)
            elif action == "play-letter":
                symbol = message.get("symbol", "")
                if not isinstance(symbol, str) or len(symbol) != 1:
                    await _send_event(
                        ws, {"type": "error", "reason": "symbol-must-be-single-character"}
                    )
                    continue
                upper = symbol.upper()
                if upper not in NATO_PHONETIC_NAMES:
                    await _send_event(
                        ws, {"type": "error", "reason": "unknown-letter", "symbol": upper}
                    )
                    continue

                # Cancel any in-flight letter sequence. Awaiting the
                # cancelled task before starting the new one preserves
                # event ordering: no overlapping letter-start frames.
                if current_letter_task is not None and not current_letter_task.done():
                    current_letter_task.cancel()
                    try:
                        await current_letter_task
                    except (asyncio.CancelledError, Exception):
                        pass

                current_letter_task = asyncio.create_task(
                    _run_letter_sequence(ws, upper, config_path, anchors_dir)
                )
            else:
                await _send_event(ws, {"type": "error", "reason": "unknown-action"})
    except ConnectionClosed:
        pass
    finally:
        # Connection closing — cancel any orphan tasks so playback stops
        # when the learner closes the tab.
        if current_session_task is not None and not current_session_task.done():
            current_session_task.cancel()
        if current_letter_task is not None and not current_letter_task.done():
            current_letter_task.cancel()


async def serve_app(
    port: int = DEFAULT_PORT,
    port_search_span: int = DEFAULT_PORT_SEARCH_SPAN,
    web_root: Path | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
    anchors_dir: Path | None = None,
) -> tuple[Any, int]:
    """Start the server and return ``(server, bound_port)``.

    The caller is responsible for keeping the event loop alive (e.g.
    ``await server.wait_closed()``). Useful for tests that want to
    drive the server programmatically.

    ``config_path`` is plumbed through so tests can point the server
    at a tmp_path config without touching the real one.
    ``anchors_dir`` is similarly plumbed so tests can use a fixture
    directory without depending on the committed NATO recordings.
    """
    chosen_port = find_available_port(port, port_search_span)
    resolved_web_root = web_root if web_root is not None else find_web_root()
    resolved_anchors_dir = anchors_dir if anchors_dir is not None else find_anchors_dir()

    process_request = _build_static_handler(resolved_web_root)

    async def _connection(ws: WebSocketServerProtocol) -> None:
        await handler(ws, config_path=config_path, anchors_dir=resolved_anchors_dir)

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
