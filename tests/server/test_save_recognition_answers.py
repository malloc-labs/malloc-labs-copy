"""Tests for the save-recognition-answers WS action.

Mirrors the koch-answers test cases in tests/server/test_app.py — happy
path round-trip, length mismatch, no-pending-record. Uses the standard
patched-playback fixture so the recognition session runs without
triggering real audio output.
"""

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
    """No-op replacement for the recognition module's _play_samples.

    The recognition flow imports sounddevice locally inside _play_samples,
    so the audio.playback monkeypatch used elsewhere in this suite does
    not catch it. Patching at the call site keeps the asyncio.to_thread
    wrapper exercised without needing PortAudio.
    """
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


async def _drain_until(ws, predicate, timeout=25.0):
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        event = json.loads(raw)
        if predicate(event):
            return event


async def test_save_recognition_answers_merges_into_record(tmp_path, patched_playback):
    """End-to-end: recognition session ends with empty answers; the save
    action rewrites the same file with the captured answers and acks."""
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
            await _drain_until(ws, lambda e: e["type"] == "session-end")

            answers = ["K", "KM", "MK", "KK", "MM"]
            await ws.send(json.dumps({"action": "save-recognition-answers", "answers": answers}))
            ack = await asyncio.wait_for(ws.recv(), timeout=5.0)

        ack_event = json.loads(ack)
        assert ack_event["type"] == "recognition-answers-saved"
        assert ack_event["answer_count"] == 5
        assert ack_event["exercise_count"] == 5

        record_dir = save_dir / "recognition"
        files = list(record_dir.rglob("recognition-*.json"))
        assert len(files) == 1
        record = json.loads(files[0].read_text())
        assert [exercise["answer"] for exercise in record["exercises"]] == answers
        # Truth fields (target + the symbols list) are untouched by the rewrite.
        assert all("target" in exercise for exercise in record["exercises"])
        assert len(record["symbols"]) > 0
    finally:
        server.close()
        await server.wait_closed()


async def test_save_recognition_answers_rejects_length_mismatch(tmp_path, patched_playback):
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
            await _drain_until(ws, lambda e: e["type"] == "session-end")

            # Only 3 answers for 5 exercises.
            await ws.send(
                json.dumps({"action": "save-recognition-answers", "answers": ["a", "b", "c"]})
            )
            ack = await asyncio.wait_for(ws.recv(), timeout=5.0)

        ack_event = json.loads(ack)
        assert ack_event["type"] == "error"
        assert ack_event["reason"] == "answers-length-mismatch"

        record_dir = save_dir / "recognition"
        files = list(record_dir.rglob("recognition-*.json"))
        assert len(files) == 1
        record = json.loads(files[0].read_text())
        # Rejected save must not have written answer fields.
        assert all("answer" not in exercise for exercise in record["exercises"])
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


async def test_save_recognition_answers_with_voice_capture(tmp_path, patched_playback):
    """voice_capture is written per exercise alongside the answer fields."""
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
            await _drain_until(ws, lambda e: e["type"] == "session-end")

            answers = ["K", "KM", "MK", "KK", "MM"]
            voice_capture = [
                [{"t": 0.7, "text": "kilo", "symbols": ["K"]}],
                [
                    {"t": 8.1, "text": "kilo", "symbols": ["K"]},
                    {"t": 14.6, "text": "mike", "symbols": ["M"]},
                ],
                [
                    {"t": 22.0, "text": "mike", "symbols": ["M"]},
                    {"t": 29.0, "text": "kilo", "symbols": ["K"]},
                ],
                [
                    {"t": 36.0, "text": "kilo", "symbols": ["K"]},
                    {"t": 42.0, "text": "kilo", "symbols": ["K"]},
                ],
                [
                    {"t": 49.0, "text": "mike", "symbols": ["M"]},
                    {"t": 56.0, "text": "mike", "symbols": ["M"]},
                ],
            ]
            await ws.send(
                json.dumps(
                    {
                        "action": "save-recognition-answers",
                        "answers": answers,
                        "voice_capture": voice_capture,
                    }
                )
            )
            ack = await asyncio.wait_for(ws.recv(), timeout=5.0)

        assert json.loads(ack)["type"] == "recognition-answers-saved"

        record_dir = save_dir / "recognition"
        files = list(record_dir.rglob("recognition-*.json"))
        record = json.loads(files[0].read_text())
        for i, exercise in enumerate(record["exercises"]):
            assert exercise["answer"] == answers[i]
            assert exercise["voice_capture"] == voice_capture[i]
    finally:
        server.close()
        await server.wait_closed()


async def test_save_recognition_answers_omits_voice_capture_field_when_not_sent(
    tmp_path, patched_playback
):
    """Save without voice_capture leaves the field absent — not [] — so
    records from phase 5 MVP saves and later 5.1 saves stay distinguishable."""
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
            await _drain_until(ws, lambda e: e["type"] == "session-end")

            answers = ["K", "KM", "MK", "KK", "MM"]
            await ws.send(json.dumps({"action": "save-recognition-answers", "answers": answers}))
            await asyncio.wait_for(ws.recv(), timeout=5.0)

        record_dir = save_dir / "recognition"
        files = list(record_dir.rglob("recognition-*.json"))
        record = json.loads(files[0].read_text())
        assert all("voice_capture" not in exercise for exercise in record["exercises"])
    finally:
        server.close()
        await server.wait_closed()


async def test_save_recognition_answers_rejects_voice_capture_length_mismatch(
    tmp_path, patched_playback
):
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
            await _drain_until(ws, lambda e: e["type"] == "session-end")

            # 5 answers, but only 3 voice_capture buckets → reject.
            await ws.send(
                json.dumps(
                    {
                        "action": "save-recognition-answers",
                        "answers": ["a", "b", "c", "d", "e"],
                        "voice_capture": [[], [], []],
                    }
                )
            )
            ack = await asyncio.wait_for(ws.recv(), timeout=5.0)

        ack_event = json.loads(ack)
        assert ack_event["type"] == "error"
        assert ack_event["reason"] == "answers-length-mismatch"
        assert "voice_capture" in ack_event["detail"]
    finally:
        server.close()
        await server.wait_closed()


async def test_save_recognition_answers_rejects_invalid_voice_capture_shape(
    tmp_path, patched_playback
):
    """Strings instead of objects, missing text/symbols, etc. → reject."""
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
            await _drain_until(ws, lambda e: e["type"] == "session-end")

            # voice_capture inner entries missing required `symbols`.
            await ws.send(
                json.dumps(
                    {
                        "action": "save-recognition-answers",
                        "answers": ["K", "KM", "MK", "KK", "MM"],
                        "voice_capture": [
                            [{"text": "kilo"}],
                            [],
                            [],
                            [],
                            [],
                        ],
                    }
                )
            )
            ack = await asyncio.wait_for(ws.recv(), timeout=5.0)

        ack_event = json.loads(ack)
        assert ack_event["type"] == "error"
        assert ack_event["reason"] == "invalid-voice-capture"
    finally:
        server.close()
        await server.wait_closed()


async def test_save_recognition_answers_is_one_shot_per_session(tmp_path, patched_playback):
    """A second save without an intervening session-end is rejected —
    the pending recognition record is cleared after the first save."""
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
            await _drain_until(ws, lambda e: e["type"] == "session-end")

            answers = ["K", "KM", "MK", "KK", "MM"]
            await ws.send(json.dumps({"action": "save-recognition-answers", "answers": answers}))
            first_ack = await asyncio.wait_for(ws.recv(), timeout=5.0)
            assert json.loads(first_ack)["type"] == "recognition-answers-saved"

            # Second save must error — pending record was cleared.
            await ws.send(json.dumps({"action": "save-recognition-answers", "answers": answers}))
            second_ack = await asyncio.wait_for(ws.recv(), timeout=5.0)

        second_event = json.loads(second_ack)
        assert second_event["type"] == "error"
        assert second_event["reason"] == "no-pending-recognition-record"
    finally:
        server.close()
        await server.wait_closed()
