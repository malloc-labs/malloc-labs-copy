"""Tests for the /api/voice/* HTTP endpoints."""

from __future__ import annotations

import asyncio
import json
import socket
import textwrap
import urllib.request
from pathlib import Path

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


async def _get_json(url: str) -> dict:
    response = await asyncio.to_thread(urllib.request.urlopen, url)
    assert response.status == 200
    assert response.headers["Content-Type"] == "application/json; charset=utf-8"
    return json.loads(response.read())


# ---------- /api/voice/lexicon -----------------------------------------


async def test_voice_lexicon_returns_merged_and_files(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[audio]\ncharacter_speed_wpm = 20\n")

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        data = await _get_json(f"http://127.0.0.1:{port}/api/voice/lexicon")
        assert data["language"] == "en"
        assert data["error"] is None
        # Every Koch curriculum symbol gets at least one phrase.
        assert "A" in data["merged"] and "alpha" in data["merged"]["A"]
        assert "X" in data["merged"] and "x ray" in data["merged"]["X"]
        # The bundled per-file shape is preserved.
        names = sorted(file["name"] for file in data["files"])
        assert names == [
            "aliases_en.json",
            "digits_en.json",
            "nato_en.json",
            "prosigns_en.json",
        ]
        for file in data["files"]:
            assert "language" in file["json"]
            assert "entries" in file["json"]
    finally:
        server.close()
        await server.wait_closed()


async def test_voice_lexicon_unknown_language_returns_error_payload(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[audio]\ncharacter_speed_wpm = 20\n")

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        data = await _get_json(f"http://127.0.0.1:{port}/api/voice/lexicon?language=zz")
        # No files for zz; merged is None and error names the problem.
        assert data["language"] == "zz"
        assert data["files"] == []
        assert data["merged"] is None
        assert "no lexicon files" in data["error"]
    finally:
        server.close()
        await server.wait_closed()


# ---------- /api/voice/status ------------------------------------------


async def test_voice_status_unconfigured(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[audio]\ncharacter_speed_wpm = 20\n")

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        data = await _get_json(f"http://127.0.0.1:{port}/api/voice/status")
        assert data["language"] == "en"
        assert data["model_path"] is None
        assert data["model_path_resolved"] is None
        assert data["model_exists"] is False
        assert data["ready"] is False
        # vosk_installed depends on the runtime; just confirm it's a bool.
        assert isinstance(data["vosk_installed"], bool)
    finally:
        server.close()
        await server.wait_closed()


async def test_voice_status_configured_but_missing_model(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(textwrap.dedent("""
            [voice]
            language = "en"
            model_path = "/does/not/exist"
            """))

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        data = await _get_json(f"http://127.0.0.1:{port}/api/voice/status")
        assert data["model_path"] == "/does/not/exist"
        assert data["model_path_resolved"] == "/does/not/exist"
        assert data["model_exists"] is False
        assert data["ready"] is False
    finally:
        server.close()
        await server.wait_closed()


async def test_voice_status_reports_ready_when_model_exists(tmp_path, monkeypatch):
    model_dir = tmp_path / "fake-model"
    model_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(textwrap.dedent(f"""
            [voice]
            language = "en"
            model_path = "{model_dir}"
            """))

    # Force vosk_installed True regardless of the runtime so the
    # readiness logic is exercised end-to-end.
    monkeypatch.setattr("copy_653.server.voice_api._is_vosk_installed", lambda: True)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        data = await _get_json(f"http://127.0.0.1:{port}/api/voice/status")
        assert data["model_exists"] is True
        assert data["vosk_installed"] is True
        assert data["ready"] is True
    finally:
        server.close()
        await server.wait_closed()
