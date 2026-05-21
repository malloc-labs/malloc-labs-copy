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
    {"action": "save-koch-answers", "answers": ["DE K", "DE MK", "..."]}
    {"action": "claim-symbol", "symbol": "U"}
    {"action": "unclaim-symbol", "symbol": "U"}
    {"action": "play-letter", "symbol": "K"}
    {"action": "play-morse-repeat", "symbol": "K"}
    {"action": "play-morse-repeat", "symbol": "K", "repeats": 3}
    {"action": "get-audio-settings"}
    {"action": "set-audio-settings", "character_wpm": 20, "effective_wpm": 10,
     "tone_shape": 2, "receiver_bed": 2, "cadence_variation": 1,
     "keyer_mode": "iambic_a", "hh_clear_enabled": false,
     "save_directory": "~/.local/share/copy_653"}
    {"action": "play-test-message", "character_wpm": 20, "effective_wpm": 10,
     "tone_shape": 2, "receiver_bed": 2, "cadence_variation": 1}
    {"action": "save-test-message", "character_wpm": 20, "effective_wpm": 10,
     "tone_shape": 2, "receiver_bed": 2, "cadence_variation": 1}
    {"action": "start-key-input"}
    {"action": "stop-key-input"}
    {"action": "request-copy-exercises"}
    {"action": "request-copy-exercises", "exercise_count": 5,
     "min_words": 4, "max_words": 7,
     "min_word_length": 1, "max_word_length": 4}
    {"action": "complete-cadence-session"}

Server → client, JSON over WS, one frame per event. Pushed
unsolicited on connect, and after every change::

    {"type": "claimed-symbols", "symbols": ["K", "M"], "suggested_next": "U",
     "evidence_ready_for_next": false, "ready_for_next": false,
     "ready_for_next_send": false}
    {"type": "audio-settings", "character_wpm": 20, "effective_wpm": 10,
     "farnsworth_enabled": true, "tone_shape": 2, "receiver_bed": 2,
     "cadence_variation": 1, "keyer_mode": "iambic_a",
     "hh_clear_enabled": false,
     "save_directory": "/home/learner/.local/share/copy_653"}

During a Koch Exercises session::

    {"type": "session-start", "mode": "exercises",
     "exercises": ["DE MK", "DE K MK", "DE KM K MMK"], "exercise_count": 3, "seed": 12345}
    {"type": "symbol", "symbol": "D", "t_on": 0.0,  "t_off": 0.24,
     "exercise_index": 1, "word_index": 1, "word": "de"}
    {"type": "symbol", "symbol": "E", "t_on": 0.34, "t_off": 0.38,
     "exercise_index": 1, "word_index": 1, "word": "de"}
    {"type": "session-end"}

After the learner types their copy answers and clicks Save, the
client sends ``save-koch-answers`` with an array parallel to the
session's ``exercises``; the engine rewrites the same JSON record with
per-exercise ``answer`` and internal ``analysis`` fields merged in and
acknowledges::

    {"type": "koch-answers-saved", "answer_count": 5, "exercise_count": 5}

A save with no pending record, an answers list of the wrong length,
or a missing record file surfaces an ``error`` frame with reason
``no-pending-koch-record``, ``answers-length-mismatch``, or
``pending-koch-record-missing`` respectively. Only one save per
session: the next save without an intervening ``session-end`` is
rejected as ``no-pending-koch-record``.

Every exercise opens with the fixed ``DE`` listening anchor (spec
§2.5) — a deliberate structural framing, not a draw from the claimed
set. The ``exercises`` field carries the full per-session truth up
front, but the UI is responsible for keeping it hidden until
``session-end``. ``exercise_index`` and ``word_index`` are 1-based,
so a UI can drive a live "Exercise N of M" indicator from each
``symbol`` event without threading session-start state through every
handler.

During a Letters playback (Koch hub → Letters page)::

    {"type": "letter-start", "symbol": "K"}
    {"type": "letter-end",   "symbol": "K"}

During a Morse-only repeat (Cadence page Alt+character preview)::

    {"type": "morse-repeat-start", "symbol": "K", "repeats": 3}
    {"type": "morse-repeat-end",   "symbol": "K"}

During Settings test-message playback/export::

    {"type": "test-message-start"}
    {"type": "test-message-end"}
    {"type": "test-message-wav-start", "filename": "...wav", "byte_length": 123}
    {"type": "test-message-wav-chunk", "data": "<base64>"}
    {"type": "test-message-wav-end", "filename": "...wav"}

During Key timing input::

    {"type": "key-input-start", "dit_note": 1, "dah_note": 2, ...}
    {"type": "sent-symbol", "symbol": "K", "pattern": "-.-", "started_at": 1.0, "ended_at": 1.9}

On copy-exercise request (Cadence page)::

    {"type": "copy-exercises", "exercises": ["K", "MK", "KMU"],
     "seed": 12345, "claimed_set": ["K", "M", "U"]}

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
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path
from typing import Any

from websockets.server import WebSocketServerProtocol, serve

from copy_653.audio.parameters import AudioParameters as AudioParameters  # noqa: F401
from copy_653.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    DEFAULT_SERVER_PORT_SEARCH_SPAN,
    KeyerSettings,  # noqa: F401  — re-exported for tests/server/test_app.py
    load_server_settings,
)
from copy_653.letters import find_anchors_dir
from copy_653.midi import KeyElement  # noqa: F401  — re-exported for tests/server/test_app.py
from copy_653.server.actions import KeyNoteSource
from copy_653.server.connection import handler
from copy_653.server.http_static import _build_static_handler, find_web_root
from copy_653.server.records import _ActiveCadenceSession as _ActiveCadenceSession  # noqa: F401
from copy_653.server.wire_events import (
    _key_event_event,  # noqa: F401  — re-exported for tests/server/test_app.py
    _sent_symbol_event,  # noqa: F401  — re-exported for tests/server/test_app.py
)

DEFAULT_HOST = DEFAULT_SERVER_HOST
DEFAULT_PORT = DEFAULT_SERVER_PORT
DEFAULT_PORT_SEARCH_SPAN = DEFAULT_SERVER_PORT_SEARCH_SPAN

logger = logging.getLogger(__name__)


def find_available_port(
    start: int,
    span: int = DEFAULT_PORT_SEARCH_SPAN,
    host: str = DEFAULT_HOST,
) -> int:
    """Return the first free TCP port in ``[start, start + span)`` on ``host``.

    Raises :class:`RuntimeError` if every candidate is occupied — per
    spec §1.5 we do not silently pick something the learner cannot
    predict. There is a small TOCTOU window between this probe and the
    actual ``serve()`` bind; for local dev that is acceptable.
    """
    if span <= 0:
        raise ValueError(f"span must be positive, got {span}")

    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return port

    raise RuntimeError(
        f"No port available in [{start}, {start + span}). "
        "Pass --port to choose a different starting point."
    )


async def serve_app(
    port: int = DEFAULT_PORT,
    port_search_span: int = DEFAULT_PORT_SEARCH_SPAN,
    host: str = DEFAULT_HOST,
    web_root: Path | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
    anchors_dir: Path | None = None,
    key_note_source: KeyNoteSource | None = None,
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
    chosen_port = find_available_port(port, port_search_span, host)
    resolved_web_root = web_root if web_root is not None else find_web_root()
    resolved_anchors_dir = anchors_dir if anchors_dir is not None else find_anchors_dir()

    process_request = _build_static_handler(resolved_web_root, config_path=config_path)

    async def _connection(ws: WebSocketServerProtocol) -> None:
        await handler(
            ws,
            config_path=config_path,
            anchors_dir=resolved_anchors_dir,
            key_note_source=key_note_source,
        )

    server = await serve(
        _connection,
        host,
        chosen_port,
        process_request=process_request,
    )
    return server, chosen_port


async def run(
    port: int | None = None,
    port_search_span: int | None = None,
    host: str | None = None,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    """Run the server forever. Entry point for ``python -m copy_653``."""
    server_settings = load_server_settings(config_path)
    resolved_host = host if host is not None else server_settings.host
    resolved_port = port if port is not None else server_settings.port
    resolved_span = (
        port_search_span if port_search_span is not None else server_settings.port_search_span
    )
    server, bound_port = await serve_app(
        port=resolved_port,
        port_search_span=resolved_span,
        host=resolved_host,
        config_path=config_path,
    )
    if bound_port != resolved_port:
        logger.info("requested port %d was in use; bound %d instead", resolved_port, bound_port)
    print(f"Copy engine listening on http://{resolved_host}:{bound_port}")
    await server.wait_closed()
