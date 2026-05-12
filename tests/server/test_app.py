"""Tests for copy_653.server.app."""

from __future__ import annotations

import asyncio
import json
import socket
import textwrap
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from websockets.client import connect as ws_connect

from copy_653.server import app

# ---------- find_available_port -----------------------------------------


def test_find_available_port_returns_starting_port_when_free():
    free_port = _grab_free_port()
    assert app.find_available_port(free_port, span=1) == free_port


def test_find_available_port_skips_busy_port():
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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------- end-to-end: HTTP + WS ---------------------------------------


@pytest.fixture
def patched_playback(monkeypatch):
    """Replace ``playback.play`` with a fast no-op so tests do not need
    PortAudio and do not actually emit sound. The asyncio.to_thread
    wrapper around it is preserved — the test still exercises the
    threading dance.
    """
    calls: list[Any] = []

    def _fake_play(samples, params):
        calls.append((samples, params))

    monkeypatch.setattr("copy_653.audio.playback.play", _fake_play)
    return calls


def _write_test_config(tmp_path: Path, claimed: list[str], duration: float = 5.0) -> Path:
    """Write a minimal config that gives us fast WPM and a short session."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(textwrap.dedent(f"""
            [audio]
            character_speed_wpm = 25
            effective_speed_wpm = 25

            [symbols]
            claimed = {claimed!r}

            [session]
            duration_seconds = {duration}
            """))
    return config_path


def _make_web_root(tmp_path: Path) -> Path:
    web_root = tmp_path / "web"
    (web_root / "css").mkdir(parents=True)
    (web_root / "js").mkdir()
    (web_root / "index.html").write_text("<!doctype html><title>t</title>")
    (web_root / "css" / "core.css").write_text("/* test */")
    (web_root / "js" / "main.js").write_text("// test")
    return web_root


async def _drain_until(ws, predicate, timeout=5.0):
    """Collect events until ``predicate(event)`` returns True. Returns
    the full list of events received (including the matching one).
    """
    received: list[dict] = []
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        event = json.loads(raw)
        received.append(event)
        if predicate(event):
            return received


async def test_serves_index_and_pushes_initial_claimed_state(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        # HTTP works.
        index = await asyncio.to_thread(urllib.request.urlopen, f"http://127.0.0.1:{port}/")
        assert index.status == 200
        assert b"<title>t</title>" in index.read()

        # Path traversal is blocked.
        try:
            await asyncio.to_thread(
                urllib.request.urlopen, f"http://127.0.0.1:{port}/../etc/passwd"
            )
            traversal_status = 200
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            traversal_status = exc.code
        assert traversal_status == 404

        # WS push: claimed-symbols on connect.
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            assert event["type"] == "claimed-symbols"
            assert event["symbols"] == ["K", "M"]
            assert event["suggested_next"] == "U"
    finally:
        server.close()
        await server.wait_closed()


async def test_start_action_runs_a_session(tmp_path, patched_playback):
    # 1.5s gives roughly two K/M symbols at 25 WPM.
    config_path = _write_test_config(tmp_path, ["K", "M"], duration=1.5)
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            # Skip the initial claimed-symbols push.
            await asyncio.wait_for(ws.recv(), timeout=2.0)

            await ws.send(json.dumps({"action": "start"}))
            events = await _drain_until(ws, lambda e: e["type"] == "session-end", timeout=10.0)

        kinds = [e["type"] for e in events]
        assert kinds[0] == "session-start"
        assert kinds[-1] == "session-end"

        start_event = events[0]
        assert isinstance(start_event["seed"], int)
        assert start_event["duration_seconds"] == 1.5
        assert all(s in ("K", "M") for s in start_event["symbols"])
        assert len(start_event["symbols"]) > 0

        symbol_events = [e for e in events if e["type"] == "symbol"]
        assert len(symbol_events) == len(start_event["symbols"])

        # Audio thread was driven once, with the configured WPM.
        assert len(patched_playback) == 1
        _, params_used = patched_playback[0]
        assert params_used.character_speed_wpm == 25
    finally:
        server.close()
        await server.wait_closed()


async def test_start_with_same_seed_replays_via_config_round_trip(tmp_path, patched_playback):
    """Two consecutive starts with different seeds ⇒ different streams.
    A session record can capture the seed; replaying is a session/
    concern, but the seed exposed here is the one that would be used.
    """
    config_path = _write_test_config(tmp_path, ["K", "M"], duration=1.5)
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)  # claimed push

            await ws.send(json.dumps({"action": "start"}))
            first = await _drain_until(ws, lambda e: e["type"] == "session-end")
            await ws.send(json.dumps({"action": "start"}))
            second = await _drain_until(ws, lambda e: e["type"] == "session-end")

        seed_a = first[0]["seed"]
        seed_b = second[0]["seed"]
        # Two consecutive sessions draw fresh seeds — overwhelmingly
        # likely to differ.
        assert seed_a != seed_b
    finally:
        server.close()
        await server.wait_closed()


async def test_start_word_detection_runs_focus_word_session(tmp_path, patched_playback):
    config_path = _write_test_config(tmp_path, ["K", "M"], duration=1.2)
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)  # claimed-symbols push

            await ws.send(json.dumps({"action": "start-word-detection"}))
            events = await _drain_until(ws, lambda e: e["type"] == "session-end", timeout=10.0)

        kinds = [event["type"] for event in events]
        assert kinds[0] == "session-start"
        assert kinds[-1] == "session-end"

        start_event = events[0]
        assert start_event["mode"] == "word-detection"
        assert start_event["focus_symbols"] == ["K", "M"]
        assert start_event["ranking"] == "rhythmic-diverse"
        assert start_event["word_count"] == len(start_event["words"])
        assert start_event["word_count"] > 0
        assert all({"k", "m"} & set(word) for word in start_event["words"])
        assert start_event["symbols"] == [
            letter.upper() for word in start_event["words"] for letter in word
        ]

        symbol_events = [event for event in events if event["type"] == "symbol"]
        assert len(symbol_events) == len(start_event["symbols"])
        assert all("word_index" in event and "word" in event for event in symbol_events)
        assert events[-1] == {"type": "session-end", "mode": "word-detection"}

        assert len(patched_playback) == 1
    finally:
        server.close()
        await server.wait_closed()


async def test_claim_symbol_persists_and_broadcasts(tmp_path, patched_playback):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)  # initial state

            await ws.send(json.dumps({"action": "claim-symbol", "symbol": "U"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)

            assert event["type"] == "claimed-symbols"
            assert event["symbols"] == ["K", "M", "U"]
            assert event["suggested_next"] == "R"

        # Persistence: a fresh load sees the claim.
        from copy_653.config import load_claimed_symbols

        assert load_claimed_symbols(config_path) == ("K", "M", "U")
    finally:
        server.close()
        await server.wait_closed()


async def test_claim_symbol_already_claimed_is_idempotent(tmp_path, patched_playback):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)

            await ws.send(json.dumps({"action": "claim-symbol", "symbol": "K"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            # Claimed list is unchanged but the event still fires so a
            # client out of sync converges.
            assert event["type"] == "claimed-symbols"
            assert event["symbols"] == ["K", "M"]
    finally:
        server.close()
        await server.wait_closed()


async def test_claim_unknown_symbol_emits_error_and_does_not_persist(tmp_path, patched_playback):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)

            await ws.send(json.dumps({"action": "claim-symbol", "symbol": "!"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            assert event["type"] == "error"
            assert event["reason"] == "unknown-symbol"

        # Config not mutated.
        from copy_653.config import load_claimed_symbols

        assert load_claimed_symbols(config_path) == ("K", "M")
    finally:
        server.close()
        await server.wait_closed()


async def test_unknown_action_emits_error(tmp_path, patched_playback):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)

            await ws.send(json.dumps({"action": "fly"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            assert event == {"type": "error", "reason": "unknown-action"}
    finally:
        server.close()
        await server.wait_closed()


async def test_get_audio_settings_returns_configured_timing(tmp_path, patched_playback):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)

            await ws.send(json.dumps({"action": "get-audio-settings"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            assert event == {
                "type": "audio-settings",
                "character_wpm": 25,
                "effective_wpm": 25,
                "farnsworth_enabled": False,
            }
    finally:
        server.close()
        await server.wait_closed()


async def test_set_audio_settings_persists_and_returns_timing(tmp_path, patched_playback):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)

            await ws.send(
                json.dumps(
                    {
                        "action": "set-audio-settings",
                        "character_wpm": 20,
                        "effective_wpm": 10,
                    }
                )
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            assert event == {
                "type": "audio-settings",
                "character_wpm": 20,
                "effective_wpm": 10,
                "farnsworth_enabled": True,
            }

        from copy_653.config import load_audio_parameters

        params = load_audio_parameters(config_path)
        assert params.character_speed_wpm == 20
        assert params.effective_speed_wpm == 10
    finally:
        server.close()
        await server.wait_closed()


async def test_set_audio_settings_rejects_invalid_timing(tmp_path, patched_playback):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)

            await ws.send(
                json.dumps(
                    {
                        "action": "set-audio-settings",
                        "character_wpm": 10,
                        "effective_wpm": 20,
                    }
                )
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            assert event["type"] == "error"
            assert event["reason"] == "invalid-audio-settings"
            assert "cannot exceed" in event["detail"]

        from copy_653.config import load_audio_parameters

        params = load_audio_parameters(config_path)
        assert params.character_speed_wpm == 25
        assert params.effective_speed_wpm == 25
    finally:
        server.close()
        await server.wait_closed()


async def test_invalid_json_returns_error(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)

            await ws.send("not json at all")
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            assert event == {"type": "error", "reason": "invalid-json"}
    finally:
        server.close()
        await server.wait_closed()


# ---------- play-letter -------------------------------------------------


@pytest.fixture
def patched_letter_playback(monkeypatch):
    """Replace ``_play_samples`` in the letters module so tests do not
    need PortAudio. The async-thread wrapper around it is preserved.
    """
    calls: list[Any] = []

    def _fake_play(samples, sample_rate_hz, output_device):
        calls.append((samples.size, sample_rate_hz))

    monkeypatch.setattr("copy_653.letters.sequence._play_samples", _fake_play)
    return calls


def _write_test_letters_config(tmp_path: Path, claimed: list[str]) -> Path:
    """Tiny config that runs the Letters sequence quickly (no gaps,
    minimum repeats). The audio table is set so claim/start tests
    sharing this fixture also stay quick."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(textwrap.dedent(f"""
            [audio]
            character_speed_wpm = 25
            effective_speed_wpm = 25

            [symbols]
            claimed = {claimed!r}

            [session]
            duration_seconds = 1.0

            [letters]
            phonetic_pairs = 1
            bare_repeats = 1
            gap_within_pair_seconds = 0.0
            gap_between_pairs_seconds = 0.0
            gap_between_bare_seconds = 0.0
            """))
    return config_path


def _make_anchors_dir(tmp_path: Path) -> Path:
    """Build a test anchors dir with a single kilo.wav fixture."""
    import struct
    import wave

    anchors_dir = tmp_path / "anchors"
    anchors_dir.mkdir()
    wav_path = anchors_dir / "kilo.wav"
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48_000)
        # 200 samples of zeros — enough to exercise the loader without
        # making the test wait on a real recording.
        w.writeframes(b"".join(struct.pack("<h", 0) for _ in range(200)))
    return anchors_dir


async def test_play_letter_runs_full_sequence(tmp_path, patched_letter_playback):
    config_path = _write_test_letters_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)
    anchors_dir = _make_anchors_dir(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
        anchors_dir=anchors_dir,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)  # claimed-symbols push

            await ws.send(json.dumps({"action": "play-letter", "symbol": "K"}))
            events = await _drain_until(ws, lambda e: e["type"] == "letter-end", timeout=5.0)

        kinds = [e["type"] for e in events]
        assert kinds[0] == "letter-start"
        assert events[0]["symbol"] == "K"
        assert kinds[-1] == "letter-end"
        assert events[-1]["symbol"] == "K"

        # Three playbacks: phonetic_pairs=1 → wav+morse, bare_repeats=1
        # → one more morse. The wav is the 200-sample fixture; the
        # morse buffers are synthesised at the configured WPM.
        assert len(patched_letter_playback) == 3
        wav_size, wav_rate = patched_letter_playback[0]
        morse_size, morse_rate = patched_letter_playback[1]
        assert wav_size == 200
        assert wav_rate == 48_000
        assert morse_size > 0
        assert patched_letter_playback[2][0] == morse_size
    finally:
        server.close()
        await server.wait_closed()


async def test_play_letter_accepts_punctuation(tmp_path, patched_letter_playback):
    config_path = _write_test_letters_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)
    anchors_dir = _make_anchors_dir(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
        anchors_dir=anchors_dir,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)  # claimed-symbols push

            await ws.send(json.dumps({"action": "play-letter", "symbol": "?"}))
            events = await _drain_until(ws, lambda e: e["type"] == "letter-end", timeout=5.0)

        assert events[0] == {"type": "letter-start", "symbol": "?"}
        assert events[-1] == {"type": "letter-end", "symbol": "?"}
        assert len(patched_letter_playback) == 3
    finally:
        server.close()
        await server.wait_closed()


async def test_play_letter_unknown_letter_emits_error(tmp_path, patched_letter_playback):
    config_path = _write_test_letters_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)
    anchors_dir = _make_anchors_dir(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
        anchors_dir=anchors_dir,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)

            # Symbols outside A-Z, 0-9, and supported punctuation have no anchor.
            await ws.send(json.dumps({"action": "play-letter", "symbol": "@"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            assert event == {"type": "error", "reason": "unknown-letter", "symbol": "@"}

        # No playback occurred.
        assert patched_letter_playback == []
    finally:
        server.close()
        await server.wait_closed()


async def test_play_letter_rejects_invalid_symbol(tmp_path, patched_letter_playback):
    config_path = _write_test_letters_config(tmp_path, ["K", "M"])
    web_root = _make_web_root(tmp_path)
    anchors_dir = _make_anchors_dir(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
        anchors_dir=anchors_dir,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)

            # Empty string is not a single character.
            await ws.send(json.dumps({"action": "play-letter", "symbol": ""}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            assert event == {"type": "error", "reason": "symbol-must-be-single-character"}

        assert patched_letter_playback == []
    finally:
        server.close()
        await server.wait_closed()
