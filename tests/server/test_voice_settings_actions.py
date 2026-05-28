"""Tests for the get-voice-settings / set-voice-settings WS actions."""

from __future__ import annotations

import asyncio
import json
import socket
import textwrap
import tomllib
from pathlib import Path

from websockets.client import connect as ws_connect

from copy_653.server import app


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


async def _drain_until(ws, type_name, timeout=2.0):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        event = json.loads(raw)
        if event.get("type") == type_name:
            return event


# ---------- get-voice-settings -----------------------------------------


async def test_get_voice_settings_returns_defaults_when_unconfigured(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[audio]\ncharacter_speed_wpm = 20\n")

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(json.dumps({"action": "get-voice-settings"}))
            event = await _drain_until(ws, "voice-settings")
            assert event["language"] == "en"
            assert event["model_path"] is None
            assert event["model_path_resolved"] is None
            assert event["model_exists"] is False
    finally:
        server.close()
        await server.wait_closed()


# ---------- set-voice-settings -----------------------------------------


async def test_set_voice_settings_writes_table_and_echoes(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[audio]\ncharacter_speed_wpm = 20\n")

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(
                json.dumps(
                    {
                        "action": "set-voice-settings",
                        "language": "en",
                        "model_path": "vosk-model-small-en-us-0.15",
                    }
                )
            )
            event = await _drain_until(ws, "voice-settings")
            assert event["language"] == "en"
            assert event["model_path"] == "vosk-model-small-en-us-0.15"
            assert event["model_path_resolved"].endswith("vosk-model-small-en-us-0.15")
            # model_exists depends on whether the user happens to have
            # this model downloaded locally — we don't care for this
            # test, only that the event reports a bool.
            assert isinstance(event["model_exists"], bool)

        # And the table actually landed on disk.
        data = tomllib.loads(config_path.read_text())
        assert data["voice"]["language"] == "en"
        assert data["voice"]["model_path"] == "vosk-model-small-en-us-0.15"
        # Pre-existing tables are preserved.
        assert data["audio"]["character_speed_wpm"] == 20
    finally:
        server.close()
        await server.wait_closed()


async def test_set_voice_settings_clears_model_path_with_null(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(textwrap.dedent("""
            [voice]
            language = "en"
            model_path = "to-be-cleared"
            """))

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(
                json.dumps({"action": "set-voice-settings", "language": "en", "model_path": None})
            )
            event = await _drain_until(ws, "voice-settings")
            assert event["model_path"] is None
            assert event["model_path_resolved"] is None
            assert event["model_exists"] is False

        data = tomllib.loads(config_path.read_text())
        assert data["voice"] == {"language": "en"}
    finally:
        server.close()
        await server.wait_closed()


async def test_set_voice_settings_treats_empty_model_path_as_clear(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(textwrap.dedent("""
            [voice]
            language = "en"
            model_path = "to-be-cleared"
            """))

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(
                json.dumps({"action": "set-voice-settings", "language": "en", "model_path": "   "})
            )
            event = await _drain_until(ws, "voice-settings")
            assert event["model_path"] is None
    finally:
        server.close()
        await server.wait_closed()


async def test_set_voice_settings_rejects_empty_language(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[audio]\ncharacter_speed_wpm = 20\n")

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(
                json.dumps({"action": "set-voice-settings", "language": "  ", "model_path": "x"})
            )
            event = await _drain_until(ws, "error")
            assert event["reason"] == "invalid-voice-settings"
            assert "language" in event["detail"]
    finally:
        server.close()
        await server.wait_closed()


async def test_set_voice_settings_reports_model_exists_when_dir_present(tmp_path):
    model_dir = tmp_path / "fake-model"
    model_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text("[audio]\ncharacter_speed_wpm = 20\n")

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(
                json.dumps(
                    {
                        "action": "set-voice-settings",
                        "language": "en",
                        "model_path": str(model_dir),
                    }
                )
            )
            event = await _drain_until(ws, "voice-settings")
            assert event["model_exists"] is True
            assert event["model_path_resolved"] == str(model_dir)
    finally:
        server.close()
        await server.wait_closed()
