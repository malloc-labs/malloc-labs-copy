"""Tests for copy_653.server.app."""

from __future__ import annotations

import asyncio
import json
import socket
import urllib.request
from typing import Any

import pytest
from websockets.client import connect as ws_connect

from copy_653.audio.parameters import AudioParameters
from copy_653.server import app

# ---------- find_available_port -----------------------------------------


def test_find_available_port_returns_starting_port_when_free():
    # Pick a port high enough to be unlikely to collide with anything.
    free_port = _grab_free_port()
    assert app.find_available_port(free_port, span=1) == free_port


def test_find_available_port_skips_busy_port():
    # Bind one socket so the first candidate is taken; the helper
    # should walk to the next.
    busy_port = _grab_free_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", busy_port))
    blocker.listen(1)
    try:
        chosen = app.find_available_port(busy_port, span=5)
        assert chosen != busy_port
        assert busy_port < chosen < busy_port + 5
    finally:
        blocker.close()


def test_find_available_port_raises_when_all_taken():
    # Bind every port in a 2-port window to force exhaustion.
    base = _grab_free_port()
    blockers = []
    try:
        for offset in range(2):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", base + offset))
            s.listen(1)
            blockers.append(s)
        with pytest.raises(RuntimeError, match="No port available"):
            app.find_available_port(base, span=2)
    finally:
        for s in blockers:
            s.close()


def test_find_available_port_rejects_non_positive_span():
    with pytest.raises(ValueError):
        app.find_available_port(8000, span=0)


def _grab_free_port() -> int:
    # Ask the OS for an ephemeral port, then immediately release it.
    # Acceptable TOCTOU for tests.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------- end-to-end: HTTP + WS ---------------------------------------


@pytest.fixture
def patched_playback(monkeypatch):
    """Replace ``playback.play`` with a fast no-op so tests do not need
    PortAudio and do not actually emit sound.

    The asyncio.to_thread wrapper around ``playback.play`` is preserved
    — the test still exercises the threading dance.
    """
    calls: list[Any] = []

    def _fake_play(samples, params):
        calls.append((samples, params))

    monkeypatch.setattr("copy_653.audio.playback.play", _fake_play)
    return calls


@pytest.mark.asyncio
async def test_serves_index_and_runs_play_session(tmp_path, patched_playback):
    # Build a minimal web root so the test does not depend on the
    # repo's actual web/ contents.
    web_root = tmp_path / "web"
    (web_root / "css").mkdir(parents=True)
    (web_root / "js").mkdir()
    (web_root / "index.html").write_text("<!doctype html><title>t</title>")
    (web_root / "css" / "core.css").write_text("/* test */")
    (web_root / "js" / "main.js").write_text("// test")

    # Use a fast WPM so the simulated session completes quickly.
    fast_params = AudioParameters(character_speed_wpm=25, effective_speed_wpm=25)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        params=fast_params,
    )
    try:
        # HTTP: GET / returns index.html.
        index = await asyncio.to_thread(urllib.request.urlopen, f"http://127.0.0.1:{port}/")
        assert index.status == 200
        assert b"<title>t</title>" in index.read()

        # HTTP: traversal attempts 404 rather than escape the web root.
        try:
            await asyncio.to_thread(
                urllib.request.urlopen, f"http://127.0.0.1:{port}/../etc/passwd"
            )
            traversal_status = 200
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            traversal_status = exc.code
        assert traversal_status == 404

        # WS: send play, collect events until session-end.
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(json.dumps({"action": "play", "symbols": "K"}))
            received: list[dict] = []
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                event = json.loads(raw)
                received.append(event)
                if event["type"] == "session-end":
                    break

        kinds = [e["type"] for e in received]
        assert kinds[0] == "session-start"
        assert kinds[-1] == "session-end"
        symbols = [e for e in received if e["type"] == "symbol"]
        assert len(symbols) == 1
        assert symbols[0]["symbol"] == "K"
        assert symbols[0]["t_on"] == pytest.approx(0.0, abs=1e-6)
        assert symbols[0]["t_off"] > 0

        # The patched playback was invoked once with the expected params.
        assert len(patched_playback) == 1
        _, params_used = patched_playback[0]
        assert params_used.character_speed_wpm == 25
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_unknown_symbol_emits_error(tmp_path, patched_playback):
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "index.html").write_text("ok")

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        params=AudioParameters(character_speed_wpm=25, effective_speed_wpm=25),
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            # '!' is not in the patterns table.
            await ws.send(json.dumps({"action": "play", "symbols": "!"}))
            error = None
            for _ in range(5):
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                event = json.loads(raw)
                if event["type"] == "error":
                    error = event
                    break
            assert error is not None
            assert error["reason"] == "unknown-symbol"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_invalid_json_returns_error(tmp_path):
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "index.html").write_text("ok")

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send("not json at all")
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            assert event == {"type": "error", "reason": "invalid-json"}
    finally:
        server.close()
        await server.wait_closed()
