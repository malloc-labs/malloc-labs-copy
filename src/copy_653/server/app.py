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
    {"action": "start-word-detection"}
    {"action": "stop"}
    {"action": "claim-symbol", "symbol": "U"}
    {"action": "unclaim-symbol", "symbol": "U"}
    {"action": "play-letter", "symbol": "K"}
    {"action": "get-audio-settings"}
    {"action": "set-audio-settings", "character_wpm": 20, "effective_wpm": 10,
     "tone_shape": 2, "receiver_bed": 2, "cadence_variation": 1}
    {"action": "play-test-message", "character_wpm": 20, "effective_wpm": 10,
     "tone_shape": 2, "receiver_bed": 2, "cadence_variation": 1}
    {"action": "save-test-message", "character_wpm": 20, "effective_wpm": 10,
     "tone_shape": 2, "receiver_bed": 2, "cadence_variation": 1}
    {"action": "start-key-input"}
    {"action": "stop-key-input"}

Server → client, JSON over WS, one frame per event. Pushed
unsolicited on connect, and after every change::

    {"type": "claimed-symbols", "symbols": ["K", "M"], "suggested_next": "U"}
    {"type": "audio-settings", "character_wpm": 20, "effective_wpm": 10,
     "farnsworth_enabled": true, "tone_shape": 2, "receiver_bed": 2,
     "cadence_variation": 1}

During a Koch Exercise session::

    {"type": "session-start", "symbols": ["K","M","K"], "duration_seconds": 30, "seed": 12345}
    {"type": "symbol", "symbol": "K", "t_on": 0.0,  "t_off": 0.18}
    {"type": "symbol", "symbol": "M", "t_on": 0.42, "t_off": 0.6}
    {"type": "session-end"}

During a Word Detection session::

    {"type": "session-start", "mode": "word-detection", "words": ["lak"], "word_count": 1, ...}
    {"type": "symbol", "symbol": "L", "t_on": 3.29, "t_off": 3.54, "word_index": 1, "word": "lak"}
    {"type": "session-end", "mode": "word-detection"}

During a Letters playback (Koch hub → Letters page)::

    {"type": "letter-start", "symbol": "K"}
    {"type": "letter-end",   "symbol": "K"}

During Settings test-message playback/export::

    {"type": "test-message-start"}
    {"type": "test-message-end"}
    {"type": "test-message-wav-start", "filename": "...wav", "byte_length": 123}
    {"type": "test-message-wav-chunk", "data": "<base64>"}
    {"type": "test-message-wav-end", "filename": "...wav"}

During Key timing input::

    {"type": "key-input-start", "dit_note": 1, "dah_note": 2, ...}
    {"type": "sent-symbol", "symbol": "K", "pattern": "-.-", "started_at": 1.0, "ended_at": 1.9}

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

import asyncio
import base64
import json
import logging
import mimetypes
import socket
import threading
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit

from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol, serve

from copy_653 import __version__, sequence
from copy_653.audio import patterns, playback, synth, texture, timing
from copy_653.audio.parameters import AudioParameters
from copy_653.audio.wav import encode_pcm16_wav
from copy_653.config import (
    DEFAULT_CONFIG_PATH,
    KeyerSettings,
    load_audio_parameters,
    load_claimed_symbols,
    load_keyer_settings,
    load_letters_config,
    load_session_duration,
    save_audio_timing,
    save_claimed_symbols,
    save_keyer_settings,
)
from copy_653.letters import (
    ANCHORED_SYMBOLS,
    find_anchors_dir,
    play_letter_sequence,
)
from copy_653.midi import (
    DecodedSymbol,
    KeyElementAssembler,
    KeyDecoder,
    MidiNoteEvent,
    iter_midi_note_events,
)
from copy_653.server.test_message_audio import build_marconi_test_message
from copy_653.server.word_detection_audio import build_word_detection_audio

DEFAULT_PORT = 8653
DEFAULT_PORT_SEARCH_SPAN = 20
# Divisible by 3 so every non-final base64 chunk can be concatenated safely.
WAV_EXPORT_CHUNK_SIZE = 245_760
KeyNoteSource = Callable[[threading.Event], Iterator[MidiNoteEvent]]

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
        """Serve static HTTP requests or allow the WebSocket upgrade."""
        # Strip the query string for static lookups; we do not use it
        # for anything in v0.
        parsed_path = urlsplit(path)
        clean_path = parsed_path.path

        # /ws is the only WS endpoint. Returning None hands control
        # back to websockets to complete the upgrade.
        if clean_path == "/ws":
            return None

        if clean_path == "/api/version":
            return _json_response({"version": __version__})

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


def _json_response(payload: dict[str, Any]) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    body = json.dumps(payload).encode("utf-8")
    return (
        HTTPStatus.OK,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
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


def _sent_symbol_event(decoded: DecodedSymbol) -> dict[str, Any]:
    """Build the Key page event for a decoded sent symbol."""
    return {
        "type": "sent-symbol",
        "symbol": decoded.symbol,
        "pattern": decoded.pattern,
        "started_at": decoded.started_at,
        "ended_at": decoded.ended_at,
        "leading_gap": decoded.leading_gap,
    }


def _key_input_start_event(settings: KeyerSettings) -> dict[str, Any]:
    """Build the Key page event announcing active MIDI input."""
    return {
        "type": "key-input-start",
        "input_name": settings.input_name,
        "dit_note": settings.dit_note,
        "dah_note": settings.dah_note,
        "straight_note": settings.straight_note,
        "dit_ms": settings.dit_ms,
        "character_gap_dits": settings.character_gap_dits,
        "trinkey_buzzer_enabled": settings.trinkey_buzzer_enabled,
    }


def _audio_settings_event_from_params(
    params: AudioParameters,
    keyer_settings: KeyerSettings | None = None,
) -> dict[str, Any]:
    """Build the learner-facing audio timing event payload."""
    if keyer_settings is None:
        keyer_settings = KeyerSettings()
    return {
        "type": "audio-settings",
        "character_wpm": params.character_speed_wpm,
        "effective_wpm": params.effective_speed_wpm,
        "farnsworth_enabled": params.effective_speed_wpm < params.character_speed_wpm,
        "tone_shape": texture.tone_shape_for_envelope_seconds(params.envelope_ramp_seconds),
        "receiver_bed": params.receiver_bed,
        "cadence_variation": params.cadence_variation,
        "trinkey_buzzer_enabled": keyer_settings.trinkey_buzzer_enabled,
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


async def _start_word_detection_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
) -> None:
    """Generate a focus-letter word stream, play it, and push word-aware timeline events."""

    audio_params = load_audio_parameters(config_path)
    claimed = load_claimed_symbols(config_path)
    duration = load_session_duration(config_path)

    if not claimed:
        await _send_event(ws, {"type": "error", "reason": "no-claimed-symbols"})
        return

    generated = sequence.generate_word_detection(
        focus_set=claimed,
        duration_seconds=duration,
        params=audio_params,
    )

    if not generated.words:
        await _send_event(
            ws,
            {"type": "error", "reason": "duration-too-short", "duration_seconds": duration},
        )
        return

    word_list = [entry.word for entry in generated.words]
    samples, timeline = build_word_detection_audio(
        word_list,
        generated.focus_set,
        audio_params,
    )

    await _send_event(
        ws,
        {
            "type": "session-start",
            "mode": "word-detection",
            "words": word_list,
            "word_count": len(word_list),
            "symbols": [symbol.symbol for symbol in generated.symbols],
            "focus_symbols": list(generated.focus_set),
            "duration_seconds": duration,
            "seed": generated.seed,
            "lexicon_schema_version": generated.lexicon_schema_version,
            "ranking": generated.ranking,
        },
    )

    audio_task = asyncio.create_task(asyncio.to_thread(playback.play, samples, audio_params))

    try:
        cursor = 0.0
        for symbol, t_on, t_off, word_index, word in timeline:
            wait = t_on - cursor
            if wait > 0:
                await asyncio.sleep(wait)
            cursor = t_on
            await _send_event(
                ws,
                {
                    "type": "symbol",
                    "symbol": symbol,
                    "t_on": t_on,
                    "t_off": t_off,
                    "word_index": word_index,
                    "word": word,
                },
            )

        await audio_task
        await _send_event(ws, {"type": "session-end", "mode": "word-detection"})

    except asyncio.CancelledError:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        audio_task.cancel()
        raise


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


async def _unclaim_symbol_action(
    ws: WebSocketServerProtocol,
    symbol: str,
    config_path: Path,
) -> None:
    """Remove ``symbol`` from the claimed set and broadcast the new state.

    Idempotent: unclaiming a symbol not in the set is a no-op (still
    rebroadcasts, so a UI out of sync converges).

    The first two symbols in KOCH_ORDER (K, M) are the permanent starting
    pair and cannot be unclaimed — the engine requires at least two symbols
    to generate a session. Attempting to unclaim them surfaces an error.
    """
    if not isinstance(symbol, str) or len(symbol) != 1:
        await _send_event(ws, {"type": "error", "reason": "symbol-must-be-single-character"})
        return

    upper = symbol.upper()
    if upper in (patterns.KOCH_ORDER[0], patterns.KOCH_ORDER[1]):
        await _send_event(
            ws, {"type": "error", "reason": "cannot-unclaim-starting-pair", "symbol": upper}
        )
        return

    claimed = load_claimed_symbols(config_path)
    if upper in claimed:
        new_claimed = tuple(s for s in claimed if s != upper)
        save_claimed_symbols(new_claimed, config_path)
        claimed = new_claimed

    await _send_event(ws, _claimed_symbols_event(claimed))


async def _get_audio_settings_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
) -> None:
    params = load_audio_parameters(config_path)
    keyer_settings = load_keyer_settings(config_path)
    await _send_event(ws, _audio_settings_event_from_params(params, keyer_settings))


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
        trinkey_buzzer_enabled = _optional_bool(
            message.get("trinkey_buzzer_enabled"),
            "trinkey_buzzer_enabled",
        )
        params = save_audio_timing(
            character_speed_wpm=character_wpm,
            effective_speed_wpm=effective_wpm,
            tone_shape=tone_shape,
            receiver_bed=receiver_bed,
            cadence_variation=cadence_variation,
            path=config_path,
        )
        keyer_settings = (
            save_keyer_settings(
                trinkey_buzzer_enabled=trinkey_buzzer_enabled,
                path=config_path,
            )
            if trinkey_buzzer_enabled is not None
            else load_keyer_settings(config_path)
        )
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

    await _send_event(ws, _audio_settings_event_from_params(params, keyer_settings))


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


async def _run_key_input_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
    note_source: KeyNoteSource | None = None,
) -> None:
    """Receive Trinkey MIDI note events, decode symbols, and push them to the page."""
    try:
        settings = load_keyer_settings(config_path)
        audio_params = load_audio_parameters(config_path)
    except ValueError as exc:
        await _send_event(ws, {"type": "error", "reason": "invalid-config", "detail": str(exc)})
        return

    decoder = KeyDecoder(
        dit_seconds=timing.dit_seconds(audio_params.character_speed_wpm),
        character_gap_seconds=timing.inter_character_seconds(audio_params),
        word_gap_seconds=timing.inter_word_seconds(audio_params),
    )
    assembler = KeyElementAssembler()
    source = note_source or (
        lambda stop: iter_midi_note_events(port_name=settings.input_name, stop_event=stop)
    )
    queue: asyncio.Queue[MidiNoteEvent | BaseException | None] = asyncio.Queue()
    stop_event = threading.Event()
    loop = asyncio.get_running_loop()

    def _queue_from_thread(item: MidiNoteEvent | BaseException | None) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:
            pass

    def _read_midi() -> None:
        try:
            for note_event in source(stop_event):
                if stop_event.is_set():
                    break
                _queue_from_thread(note_event)
        except BaseException as exc:
            _queue_from_thread(exc)
        finally:
            _queue_from_thread(None)

    thread = threading.Thread(target=_read_midi, name="copy-653-key-midi", daemon=True)
    thread.start()
    character_gap_seconds = timing.inter_character_seconds(audio_params)

    await _send_event(ws, _key_input_start_event(settings))

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=character_gap_seconds)
            except asyncio.TimeoutError:
                await _flush_key_symbol(ws, decoder)
                continue

            if item is None:
                await _flush_key_symbol(ws, decoder)
                return
            if isinstance(item, BaseException):
                reason = (
                    "key-input-unavailable" if isinstance(item, ImportError) else "key-input-failed"
                )
                await _send_event(ws, {"type": "error", "reason": reason, "detail": str(item)})
                return

            element = assembler.push(item, settings)
            if element is None:
                continue

            try:
                decoded = decoder.push(element)
            except ValueError as exc:
                await _send_event(
                    ws,
                    {"type": "error", "reason": "key-input-decode-failed", "detail": str(exc)},
                )
                decoder.reset()
                continue
            if decoded is not None:
                await _send_event(ws, _sent_symbol_event(decoded))
    finally:
        stop_event.set()
        await asyncio.to_thread(thread.join, 1.0)


async def _flush_key_symbol(ws: WebSocketServerProtocol, decoder: KeyDecoder) -> None:
    try:
        decoded = decoder.tick(asyncio.get_running_loop().time())
    except ValueError as exc:
        await _send_event(
            ws, {"type": "error", "reason": "key-input-decode-failed", "detail": str(exc)}
        )
        decoder.reset()
        return
    if decoded is not None:
        await _send_event(ws, _sent_symbol_event(decoded))


def _audio_params_from_settings_message(message: dict[str, Any]) -> AudioParameters:
    character_wpm = _strict_positive_int(message.get("character_wpm"), "character_wpm")
    effective_wpm = _strict_positive_int(message.get("effective_wpm"), "effective_wpm")
    tone_shape = _strict_bounded_int(
        message.get("tone_shape"),
        "tone_shape",
        texture.MIN_TONE_SHAPE,
        texture.MAX_TONE_SHAPE,
    )
    receiver_bed = _strict_bounded_int(
        message.get("receiver_bed"),
        "receiver_bed",
        texture.MIN_RECEIVER_BED,
        texture.MAX_RECEIVER_BED,
    )
    cadence_variation = _strict_bounded_int(
        message.get("cadence_variation"),
        "cadence_variation",
        texture.MIN_CADENCE_VARIATION,
        texture.MAX_CADENCE_VARIATION,
    )
    return AudioParameters(
        character_speed_wpm=character_wpm,
        effective_speed_wpm=effective_wpm,
        envelope_ramp_seconds=texture.envelope_seconds_for_tone_shape(tone_shape),
        receiver_bed=receiver_bed,
        cadence_variation=cadence_variation,
    )


def _strict_positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _strict_bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    parsed = _optional_bounded_int(value, field, minimum, maximum)
    if parsed is None:
        raise ValueError(f"{field} must be an integer from {minimum} to {maximum}")
    return parsed


def _optional_bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field} must be an integer from {minimum} to {maximum}")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer from {minimum} to {maximum}")
    return value


def _optional_bool(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


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
    key_note_source: KeyNoteSource | None = None,
) -> None:
    """Top-level WS connection handler. Dispatches incoming JSON commands."""
    if anchors_dir is None:
        anchors_dir = find_anchors_dir()

    # Per-connection state: in-flight session task and letter task.
    # A stop action cancels the session task; a new play-letter cancels
    # and replaces the letter task.
    current_session_task: asyncio.Task[None] | None = None
    current_letter_task: asyncio.Task[None] | None = None
    current_test_message_task: asyncio.Task[None] | None = None
    current_key_input_task: asyncio.Task[None] | None = None

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
            if action in {"start", "start-word-detection"}:
                # Cancel any in-flight session before starting a new one.
                if current_session_task is not None and not current_session_task.done():
                    current_session_task.cancel()
                    try:
                        await current_session_task
                    except (asyncio.CancelledError, Exception):
                        pass

                async def _run_session() -> None:
                    try:
                        if action == "start-word-detection":
                            await _start_word_detection_action(ws, config_path)
                        else:
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
            elif action == "unclaim-symbol":
                await _unclaim_symbol_action(ws, message.get("symbol", ""), config_path)
            elif action == "get-audio-settings":
                await _get_audio_settings_action(ws, config_path)
            elif action == "set-audio-settings":
                await _set_audio_settings_action(ws, message, config_path)
            elif action == "start-key-input":
                if current_key_input_task is not None and not current_key_input_task.done():
                    current_key_input_task.cancel()
                    try:
                        await current_key_input_task
                    except (asyncio.CancelledError, Exception):
                        pass
                current_key_input_task = asyncio.create_task(
                    _run_key_input_action(ws, config_path, key_note_source)
                )
            elif action == "stop-key-input":
                if current_key_input_task is not None and not current_key_input_task.done():
                    current_key_input_task.cancel()
            elif action == "play-test-message":
                if current_test_message_task is not None and not current_test_message_task.done():
                    current_test_message_task.cancel()
                    try:
                        await current_test_message_task
                    except (asyncio.CancelledError, Exception):
                        pass

                current_test_message_task = asyncio.create_task(
                    _play_test_message_action(ws, message)
                )
            elif action == "save-test-message":
                await _save_test_message_action(ws, message)
            elif action == "play-letter":
                symbol = message.get("symbol", "")
                if not isinstance(symbol, str) or len(symbol) != 1:
                    await _send_event(
                        ws, {"type": "error", "reason": "symbol-must-be-single-character"}
                    )
                    continue
                upper = symbol.upper()
                if upper not in ANCHORED_SYMBOLS:
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
        if current_test_message_task is not None and not current_test_message_task.done():
            current_test_message_task.cancel()
        if current_key_input_task is not None and not current_key_input_task.done():
            current_key_input_task.cancel()


async def serve_app(
    port: int = DEFAULT_PORT,
    port_search_span: int = DEFAULT_PORT_SEARCH_SPAN,
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
    chosen_port = find_available_port(port, port_search_span)
    resolved_web_root = web_root if web_root is not None else find_web_root()
    resolved_anchors_dir = anchors_dir if anchors_dir is not None else find_anchors_dir()

    process_request = _build_static_handler(resolved_web_root)

    async def _connection(ws: WebSocketServerProtocol) -> None:
        await handler(
            ws,
            config_path=config_path,
            anchors_dir=resolved_anchors_dir,
            key_note_source=key_note_source,
        )

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
