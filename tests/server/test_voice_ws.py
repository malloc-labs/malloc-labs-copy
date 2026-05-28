"""Tests for the /voice/ws endpoint.

The recogniser is faked via the ``recognizer_factory`` parameter on
:func:`copy_653.server.voice_ws.voice_handler`, but we exercise the
full path-based dispatch in :func:`copy_653.server.app.serve_app` by
opening a real WebSocket from a real client.
"""

from __future__ import annotations

import asyncio
import json
import socket
import textwrap
from pathlib import Path

import pytest
from websockets.client import connect as ws_connect

from copy_653.server import app
from copy_653.server import voice_ws as voice_ws_module
from copy_653.voice import FinalResult, PartialResult

# ---------- helpers ----------------------------------------------------


def _grab_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _make_web_root(tmp_path: Path) -> Path:
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "index.html").write_text("<!doctype html><title>t</title>")
    return web_root


class _ScriptedRecognizer:
    """Recogniser stub used in the WS-level integration tests."""

    def __init__(self, events_per_frame: list[list[object]]) -> None:
        self._events_per_frame = list(events_per_frame)
        self.frames_received: list[bytes] = []
        self.reset_calls = 0

    def feed_pcm(self, frame: bytes) -> list[object]:
        self.frames_received.append(frame)
        if not self._events_per_frame:
            return []
        return self._events_per_frame.pop(0)

    def reset(self) -> None:
        self.reset_calls += 1


def _factory_returning(recognizer: _ScriptedRecognizer):
    def _factory(_settings):
        return recognizer

    return _factory


def _factory_raising(error: Exception):
    def _factory(_settings):
        raise error

    return _factory


# ---------- voice not configured (no [voice] table) --------------------


async def test_voice_unconfigured_returns_error_and_closes(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[audio]\ncharacter_speed_wpm = 20\n")
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/voice/ws") as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            assert event == {
                "type": "error",
                "reason": "voice-unavailable",
                "message": (
                    "[voice].model_path is not configured; "
                    "voice input is disabled until a model path is set"
                ),
            }
            # Server closes the connection after the error frame.
            with pytest.raises(Exception):
                await asyncio.wait_for(ws.recv(), timeout=2.0)
    finally:
        server.close()
        await server.wait_closed()


# ---------- voice present-but-broken (factory raises) ------------------


async def test_voice_factory_error_returns_named_message(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(textwrap.dedent("""
            [voice]
            language = "en"
            model_path = "/does/not/exist"
            """))
    web_root = _make_web_root(tmp_path)

    from copy_653.voice import VoiceUnavailableError

    # Patch the default factory used inside voice_handler.
    original_handler = voice_ws_module.voice_handler

    async def patched_handler(ws, *, config_path, recognizer_factory=None):
        return await original_handler(
            ws,
            config_path=config_path,
            recognizer_factory=_factory_raising(VoiceUnavailableError("model gone")),
        )

    monkeypatch.setattr(voice_ws_module, "voice_handler", patched_handler)
    # serve_app captured the original reference at import; we need to
    # patch where serve_app reaches for it.
    monkeypatch.setattr("copy_653.server.app.voice_handler", patched_handler)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/voice/ws") as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            assert json.loads(raw) == {
                "type": "error",
                "reason": "voice-unavailable",
                "message": "model gone",
            }
    finally:
        server.close()
        await server.wait_closed()


# ---------- happy path: scripted recogniser ----------------------------


async def test_voice_ws_streams_partial_then_final(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(textwrap.dedent("""
            [voice]
            language = "en"
            model_path = "/tmp/anything"
            """))
    web_root = _make_web_root(tmp_path)

    rec = _ScriptedRecognizer(
        events_per_frame=[
            [PartialResult(text="al", symbols=())],
            [FinalResult(text="uniform kilo mike", symbols=("U", "K", "M"))],
        ]
    )

    original_handler = voice_ws_module.voice_handler

    async def patched_handler(ws, *, config_path, recognizer_factory=None):
        return await original_handler(
            ws,
            config_path=config_path,
            recognizer_factory=_factory_returning(rec),
        )

    monkeypatch.setattr("copy_653.server.app.voice_handler", patched_handler)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/voice/ws") as ws:
            # Recogniser-constructed handshake before any PCM is sent.
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            assert json.loads(raw) == {"type": "ready"}

            await ws.send(b"\x00\x00" * 256)
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            assert json.loads(raw) == {"type": "partial", "text": "al", "symbols": []}

            await ws.send(b"\x00\x00" * 256)
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            assert json.loads(raw) == {
                "type": "final",
                "text": "uniform kilo mike",
                "symbols": ["U", "K", "M"],
            }

            await ws.send("reset")
            # No event from reset itself; just confirm the recogniser saw it.
            await asyncio.sleep(0.05)
            assert rec.reset_calls == 1
            assert len(rec.frames_received) == 2
    finally:
        server.close()
        await server.wait_closed()


# ---------- non-voice WS path still works ------------------------------


async def test_root_ws_path_still_uses_main_handler(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(textwrap.dedent("""
            [audio]
            character_speed_wpm = 25

            [symbols]
            claimed = ["K", "M"]
            """))
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            # The main handler pushes claimed-symbols on connect.
            assert event["type"] == "claimed-symbols"
    finally:
        server.close()
        await server.wait_closed()
