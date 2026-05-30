"""Tests for the live Symbol Recognition exercise-completion loop."""

from __future__ import annotations

import asyncio
import json
import socket
import textwrap
from pathlib import Path
from typing import Any

import pytest
from websockets.client import connect as ws_connect

from copy_653.server import app


@pytest.fixture
def patched_playback(monkeypatch):
    """No-op replacement for the recognition module's _play_samples."""
    calls: list[Any] = []

    def _fake_play(samples, sample_rate_hz, output_device):
        calls.append((getattr(samples, "size", None), sample_rate_hz))

    monkeypatch.setattr("copy_653.server.recognition_actions._play_samples", _fake_play)
    return calls


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


def _write_recognition_config(tmp_path: Path, save_dir: Path) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(textwrap.dedent(f"""
            [audio]
            character_speed_wpm = 25
            effective_speed_wpm = 25
            tone_frequency_hz = 600
            amplitude = 0.3

            [symbols]
            claimed = ["K", "M"]

            [recognition]
            say_before = false
            morse_count = 1
            recognition_time_ms = 0
            say_after = false

            [storage]
            save_directory = "{save_dir}"
            """))
    return config_path


async def _recv_event(ws, timeout=25.0) -> dict[str, Any]:
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


async def _complete_live_recognition_session(ws, *, first_answer: str | None = None):
    by_exercise: dict[int, list[str]] = {}
    completed = 0
    while True:
        event = await _recv_event(ws)
        if event["type"] == "symbol":
            by_exercise.setdefault(event["exercise_index"], []).append(event["symbol"])
        elif event["type"] == "recognition-exercise-end":
            exercise_index = event["exercise_index"]
            target = "".join(by_exercise.get(exercise_index, []))
            answer = first_answer if exercise_index == 1 and first_answer is not None else target
            await ws.send(
                json.dumps(
                    {
                        "action": "complete-recognition-exercise",
                        "exercise_index": exercise_index,
                        "answer": answer,
                        "voice_capture": [
                            {
                                "t": 0.1 * exercise_index,
                                "text": answer,
                                "symbols": list(answer),
                            }
                        ],
                    }
                )
            )
            completed += 1
        elif event["type"] == "session-end":
            return by_exercise, completed


async def test_live_recognition_completion_writes_final_record(tmp_path, patched_playback):
    save_dir = tmp_path / "records"
    config_path = _write_recognition_config(tmp_path, save_dir)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)
            await ws.send(json.dumps({"action": "start-recognition"}))
            targets, completed = await _complete_live_recognition_session(ws)

        assert completed == 5
        record_dir = save_dir / "recognition"
        files = list(record_dir.rglob("session-*.json"))
        assert len(files) == 1
        assert files[0].parent.name.startswith("set-")
        record = json.loads(files[0].read_text())
        assert len(record["exercises"]) == 5
        assert all("answer" in exercise for exercise in record["exercises"])
        assert all("analysis" in exercise for exercise in record["exercises"])
        assert ["".join(targets[index]) for index in range(1, 6)] == [
            exercise["answer"] for exercise in record["exercises"]
        ]
    finally:
        server.close()
        await server.wait_closed()


async def test_live_recognition_repeats_after_incorrect_answer(tmp_path, patched_playback):
    save_dir = tmp_path / "records"
    config_path = _write_recognition_config(tmp_path, save_dir)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)
            await ws.send(json.dumps({"action": "start-recognition"}))
            targets, completed = await _complete_live_recognition_session(ws, first_answer="X")

        assert completed == 5
        assert targets[2] == targets[1]
        record_dir = save_dir / "recognition"
        files = list(record_dir.rglob("session-*.json"))
        record = json.loads(files[0].read_text())
        assert record["exercises"][0]["answer"] == "X"
        assert record["exercises"][1]["target"] == record["exercises"][0]["target"]
    finally:
        server.close()
        await server.wait_closed()


async def test_save_recognition_answers_without_pending_record_errors(tmp_path):
    save_dir = tmp_path / "records"
    config_path = _write_recognition_config(tmp_path, save_dir)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=_make_web_root(tmp_path),
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)
            await ws.send(json.dumps({"action": "save-recognition-answers", "answers": []}))
            ack = await asyncio.wait_for(ws.recv(), timeout=5.0)

        ack_event = json.loads(ack)
        assert ack_event["type"] == "error"
        assert ack_event["reason"] == "no-pending-recognition-record"
    finally:
        server.close()
        await server.wait_closed()
