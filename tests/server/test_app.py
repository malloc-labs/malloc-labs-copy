"""Tests for copy_653.server.app."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import socket
import textwrap
import tomllib
import urllib.error
import urllib.request
import wave
import zipfile
from pathlib import Path
from typing import Any

import pytest
from websockets.client import connect as ws_connect

from copy_653 import __version__
from copy_653.midi import DecodedSymbol, MidiNoteEvent
from copy_653.server import app

# ---------- find_available_port -----------------------------------------


def test_find_available_port_returns_starting_port_when_free():
    free_port = _grab_free_port()
    assert app.find_available_port(free_port, span=1) == free_port


def test_find_available_port_uses_reusable_probe_socket(monkeypatch):
    calls = []

    class ProbeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def setsockopt(self, level, option, value):
            calls.append((level, option, value))

        def bind(self, address):
            self.address = address

    monkeypatch.setattr(app.socket, "socket", lambda *args: ProbeSocket())

    assert app.find_available_port(8653, span=1) == 8653
    assert (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) in calls


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


def _write_test_config_with_keyer(tmp_path: Path) -> Path:
    config_path = _write_test_config(tmp_path, ["K", "M"])
    config_path.write_text(config_path.read_text() + textwrap.dedent("""

            [midi.key]
            input_name = "TRRS Trinkey"
            dit_note = 1
            dah_note = 2
            straight_note = 0
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


def test_sent_symbol_event_serializes_decoder_output():
    event = app._sent_symbol_event(
        DecodedSymbol(
            pattern="-.-",
            symbol="K",
            started_at=1.2,
            ended_at=1.9,
        )
    )

    assert event == {
        "type": "sent-symbol",
        "symbol": "K",
        "pattern": "-.-",
        "started_at": 1.2,
        "ended_at": 1.9,
        "leading_gap": "none",
    }


def test_sent_symbol_event_allows_unknown_pattern():
    event = app._sent_symbol_event(
        DecodedSymbol(
            pattern="......",
            symbol=None,
            started_at=1.2,
            ended_at=2.3,
        )
    )

    assert event["type"] == "sent-symbol"
    assert event["symbol"] is None
    assert event["pattern"] == "......"
    assert event["leading_gap"] == "none"


def test_key_event_event_reports_mapped_note_and_release_measurement():
    event = app._key_event_event(
        MidiNoteEvent(note=2, pressed=False, timestamp=1.2),
        app.KeyerSettings(dit_note=1, dah_note=2),
        app.AudioParameters(character_speed_wpm=20, effective_speed_wpm=10),
        app.KeyElement(kind="dah", started_at=1.0, ended_at=1.18),
    )

    assert event == {
        "type": "key-event",
        "kind": "dah",
        "note": 2,
        "pressed": False,
        "timestamp": 1.2,
        "tone_frequency_hz": 600,
        "amplitude": 0.3,
        "envelope_ramp_ms": 5.0,
        "duration_ms": 180.0,
        "ratio_dits": 3.0,
    }


def test_key_event_event_ignores_unmapped_note():
    assert (
        app._key_event_event(
            MidiNoteEvent(note=64, pressed=True, timestamp=1.0),
            app.KeyerSettings(dit_note=1, dah_note=2),
            app.AudioParameters(),
        )
        is None
    )


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

        version = await asyncio.to_thread(
            urllib.request.urlopen, f"http://127.0.0.1:{port}/api/version"
        )
        assert version.status == 200
        assert version.headers["Content-Type"] == "application/json; charset=utf-8"
        assert json.loads(version.read()) == {"version": __version__}

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


async def test_api_koch_exercises_lists_records_newest_first(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    koch_dir = save_dir / "koch-exercise"
    koch_dir.mkdir(parents=True)
    older = {
        "schema_version": "1.3",
        "mode": "koch-exercise",
        "started_at": "2026-05-15T09:00:00.000Z",
        "ended_at": "2026-05-15T09:00:30.000Z",
        "claimed_set": ["K", "M"],
        "seed": 1,
        "exercises": [],
        "symbols": [],
        "answers": [],
    }
    newer = dict(older)
    newer["started_at"] = "2026-05-15T10:00:00.000Z"
    newer["claimed_set"] = ["K", "M", "U"]
    (koch_dir / "koch-exercise-20260515T090000Z.json").write_text(json.dumps(older))
    (koch_dir / "koch-exercise-20260515T100000Z.json").write_text(json.dumps(newer))
    # A non-koch file in the same directory must be ignored.
    (koch_dir / "stray.txt").write_text("not json")

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen, f"http://127.0.0.1:{port}/api/koch-exercises"
        )
        assert response.status == 200
        assert response.headers["Content-Type"] == "application/json; charset=utf-8"
        payload = json.loads(response.read())
        assert payload["save_directory"] == str(save_dir)
        records = payload["records"]
        assert len(records) == 2
        # Newest first.
        assert records[0]["started_at"] == "2026-05-15T10:00:00.000Z"
        assert records[0]["claimed_set"] == ["K", "M", "U"]
        assert records[0]["filename"] == "koch-exercise-20260515T100000Z.json"
        assert records[1]["started_at"] == "2026-05-15T09:00:00.000Z"
        assert records[1]["claimed_set"] == ["K", "M"]
    finally:
        server.close()
        await server.wait_closed()


async def test_api_koch_exercise_returns_full_record(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    koch_dir = save_dir / "koch-exercise"
    koch_dir.mkdir(parents=True)
    record = {
        "schema_version": "2.0",
        "engine_version": "0.7.1",
        "mode": "koch-exercise",
        "started_at": "2026-05-15T10:00:00.000Z",
        "ended_at": "2026-05-15T10:01:30.000Z",
        "audio": {
            "character_speed_wpm": 20,
            "effective_speed_wpm": 10,
            "tone_frequency_hz": 600,
        },
        "claimed_set": ["K", "M"],
        "seed": 7,
        "generation": {
            "profile_version": "koch-burden-v1",
            "claimed_set_key": "K M",
            "set_id": "20260515T100000Z",
            "set_session": 3,
            "candidate_count": 20,
            "bands": [{"index": 1, "gear": 0}, {"index": 2, "gear": 0}],
        },
        "exercises": [
            {
                "index": 1,
                "played": "DE K",
                "core": "K",
                "burden_score": 20,
                "burden_band": 1,
                "gear": 0,
                "answer": "DE K",
                "analysis": {"version": "koch-analysis-v1", "saved": True},
            },
            {
                "index": 2,
                "played": "DE M",
                "core": "M",
                "burden_score": 20,
                "burden_band": 2,
                "gear": 0,
                "answer": "DE N",
                "analysis": {"version": "koch-analysis-v1", "saved": True},
            },
        ],
        "symbols": [],
    }
    filename = "2026/05/set-20260515T100000Z/session-03.json"
    (koch_dir / filename).parent.mkdir(parents=True)
    (koch_dir / filename).write_text(json.dumps(record))

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/koch-exercise?file={filename}",
        )
        assert response.status == 200
        assert response.headers["Content-Type"] == "application/json; charset=utf-8"
        payload = json.loads(response.read())
        assert payload["mode"] == "koch-exercise"
        assert payload["exercises"][0]["played"] == "DE K"
        assert payload["exercises"][0]["answer"] == "DE K"
        assert payload["audio"]["character_speed_wpm"] == 20
    finally:
        server.close()
        await server.wait_closed()


async def test_api_koch_exercise_rejects_path_traversal(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        for bad in (
            "../../etc/passwd",
            "../config.toml",
            "koch-exercise-/../../config.toml",
            "anything.json",
            "",
        ):
            url = f"http://127.0.0.1:{port}/api/koch-exercise?file={urllib.parse.quote(bad)}"
            try:
                await asyncio.to_thread(urllib.request.urlopen, url)
                status = 200
            except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
                status = exc.code
            assert status in (400, 404), (bad, status)
    finally:
        server.close()
        await server.wait_closed()


async def test_api_koch_exercise_missing_file_returns_404(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    (save_dir / "koch-exercise").mkdir(parents=True)
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        url = (
            f"http://127.0.0.1:{port}/api/koch-exercise" "?file=koch-exercise-20990101T000000Z.json"
        )
        try:
            await asyncio.to_thread(urllib.request.urlopen, url)
            status = 200
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            status = exc.code
        assert status == 404
    finally:
        server.close()
        await server.wait_closed()


async def test_api_koch_exercises_returns_empty_when_directory_missing(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen, f"http://127.0.0.1:{port}/api/koch-exercises"
        )
        payload = json.loads(response.read())
        assert payload["save_directory"] == str(save_dir)
        assert payload["records"] == []
    finally:
        server.close()
        await server.wait_closed()


async def test_api_cadence_sends_lists_records_newest_first(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    cadence_dir = save_dir / "cadence-send"
    cadence_dir.mkdir(parents=True)
    older = {
        "schema_version": "2.0",
        "mode": "cadence-send",
        "started_at": "2026-05-15T09:00:00.000Z",
        "ended_at": "2026-05-15T09:00:30.000Z",
        "claimed_set": ["K", "M"],
        "seed": 1,
        "generation": {"claimed_set_key": "K M"},
        "exercises": [{"index": 1, "target": "K"}],
        "sent": [],
        "key_events": [],
    }
    newer = dict(older)
    newer["started_at"] = "2026-05-15T10:00:00.000Z"
    newer["claimed_set"] = ["K", "M", "U"]
    newer["exercises"] = [{"index": 1, "target": "KM"}, {"index": 2, "target": "MU"}]
    (cadence_dir / "cadence-send-20260515T090000Z.json").write_text(json.dumps(older))
    (cadence_dir / "cadence-send-20260515T100000Z.json").write_text(json.dumps(newer))

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen, f"http://127.0.0.1:{port}/api/cadence-sends"
        )
        payload = json.loads(response.read())
        assert payload["save_directory"] == str(save_dir)
        records = payload["records"]
        assert len(records) == 2
        assert records[0]["filename"] == "cadence-send-20260515T100000Z.json"
        assert records[0]["claimed_set"] == ["K", "M", "U"]
        assert records[0]["exercise_count"] == 2
        assert records[1]["filename"] == "cadence-send-20260515T090000Z.json"
    finally:
        server.close()
        await server.wait_closed()


async def test_api_cadence_send_returns_full_record(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    cadence_dir = save_dir / "cadence-send"
    cadence_dir.mkdir(parents=True)
    filename = "cadence-send-20260515T100000Z.json"
    record = {
        "schema_version": "2.0",
        "mode": "cadence-send",
        "started_at": "2026-05-15T10:00:00.000Z",
        "ended_at": "2026-05-15T10:01:00.000Z",
        "claimed_set": ["K", "M"],
        "seed": 7,
        "generation": {"profile_version": "cadence-burden-v1", "claimed_set_key": "K M"},
        "exercises": [{"index": 1, "target": "KM", "analysis": {"saved": True}}],
        "sent": [],
        "key_events": [],
    }
    (cadence_dir / filename).write_text(json.dumps(record))

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/cadence-send?file={filename}",
        )
        payload = json.loads(response.read())
        assert payload["mode"] == "cadence-send"
        assert payload["exercises"][0]["target"] == "KM"
    finally:
        server.close()
        await server.wait_closed()


async def test_api_backup_returns_zip_of_record_directory(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    koch_dir = save_dir / "koch-exercise"
    koch_dir.mkdir(parents=True)
    (koch_dir / "koch-exercise-20260515T090000Z.json").write_text('{"mode":"koch-exercise"}')
    (koch_dir / "koch-exercise-20260515T100000Z.json").write_text('{"mode":"koch-exercise"}')
    # Stray non-record file in the same directory is excluded — only
    # files matching the canonical glob make it into the zip.
    (koch_dir / "stray.txt").write_text("ignored")

    cadence_dir = save_dir / "cadence-send"
    cadence_dir.mkdir(parents=True)
    (cadence_dir / "cadence-send-20260515T120000Z.json").write_text('{"mode":"cadence-send"}')

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        # Happy path: koch-exercise kind returns a zip with two
        # records, in the koch-exercise/ subpath, and announces the
        # file count via the X-Copy-Backup-File-Count header.
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/backup?kind=koch-exercise",
        )
        assert response.status == 200
        assert response.headers["Content-Type"] == "application/zip"
        assert response.headers["X-Copy-Backup-File-Count"] == "2"
        disposition = response.headers["Content-Disposition"]
        assert disposition.startswith('attachment; filename="copy-653-koch-exercise-backup-')
        assert disposition.endswith('.zip"')
        body = response.read()
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            assert sorted(archive.namelist()) == [
                "koch-exercise/koch-exercise-20260515T090000Z.json",
                "koch-exercise/koch-exercise-20260515T100000Z.json",
            ]

        # cadence-send kind backs up its own directory only.
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/backup?kind=cadence-send",
        )
        assert response.headers["X-Copy-Backup-File-Count"] == "1"
        with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            assert archive.namelist() == ["cadence-send/cadence-send-20260515T120000Z.json"]

        # Unknown kind is a 400 — the endpoint refuses to guess.
        try:
            await asyncio.to_thread(
                urllib.request.urlopen,
                f"http://127.0.0.1:{port}/api/backup?kind=mystery",
            )
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            assert exc.code == 400
    finally:
        server.close()
        await server.wait_closed()


async def test_api_backup_empty_directory_returns_empty_zip(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/backup?kind=koch-exercise",
        )
        assert response.status == 200
        assert response.headers["X-Copy-Backup-File-Count"] == "0"
        with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            assert archive.namelist() == []
    finally:
        server.close()
        await server.wait_closed()


async def test_api_koch_band_evidence_returns_recent_per_band_rollup(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    koch_dir = save_dir / "koch-exercise"
    koch_dir.mkdir(parents=True)

    def _exercise(burden_band: int, fraction: float) -> dict:
        return {
            "index": burden_band,
            "burden_band": burden_band,
            "burden_score": 50,
            "analysis": {
                "version": "koch-analysis-v1",
                "saved": True,
                "combined_fraction": fraction,
                "band_state": "exact" if fraction >= 1.0 else "low",
            },
        }

    def _record(stamp: str, key: str, fraction: float) -> dict:
        return {
            "schema_version": "2.0",
            "mode": "koch-exercise",
            "started_at": stamp,
            "claimed_set": key.split(),
            "generation": {"claimed_set_key": key},
            "exercises": [_exercise(1, fraction)],
            "symbols": [],
        }

    (koch_dir / "koch-exercise-20260518T130000Z.json").write_text(
        json.dumps(_record("2026-05-18T13:00:00.000Z", "K M", 1.0))
    )
    (koch_dir / "koch-exercise-20260518T140000Z.json").write_text(
        json.dumps(_record("2026-05-18T14:00:00.000Z", "K M", 1.0))
    )
    # An unrelated claimed set must not contribute to the K M rollup.
    (koch_dir / "koch-exercise-20260518T150000Z.json").write_text(
        json.dumps(_record("2026-05-18T15:00:00.000Z", "K M U", 0.5))
    )

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        # No query param: endpoint picks the most-recent saved session's
        # claimed_set_key (here "K M U"), which has only the one record.
        response = await asyncio.to_thread(
            urllib.request.urlopen, f"http://127.0.0.1:{port}/api/koch-band-evidence"
        )
        payload = json.loads(response.read())
        assert payload["claimed_set_key"] == "K M U"
        assert payload["session_count"] == 1

        # Explicit key: K M has two strong sessions for band 1.
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/koch-band-evidence?claimed_set_key=K%20M",
        )
        payload = json.loads(response.read())
        assert payload["claimed_set_key"] == "K M"
        assert payload["session_count"] == 2
        assert payload["sessions_used"] == 2
        assert payload["bands"][0]["burden_band"] == 1
        assert payload["bands"][0]["current_gear"] == 0
        assert payload["bands"][0]["recent_fractions"] == [1.0, 1.0]
        assert payload["bands"][0]["strong_streak"] == 2
    finally:
        server.close()
        await server.wait_closed()


async def test_api_koch_burden_profile_returns_symbol_rows(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    koch_dir = save_dir / "koch-exercise"
    koch_dir.mkdir(parents=True)

    def _exercise(index: int, played: str, answer: str, correct: int) -> dict:
        return {
            "index": index,
            "played": played,
            "answer": answer,
            "burden_band": 1,
            "burden_score": 50,
            "analysis": {
                "version": "koch-analysis-v1",
                "saved": True,
                "normalized_answer": answer,
                "symbol_correct_units": correct,
                "symbol_available_units": 2,
                "spacing_correct_units": 0,
                "spacing_available_units": 0,
                "combined_fraction": correct / 2,
                "band_state": "exact" if correct == 2 else "low",
            },
        }

    def _record(stamp: str, exercise: dict) -> dict:
        return {
            "schema_version": "2.0",
            "mode": "koch-exercise",
            "started_at": stamp,
            "claimed_set": ["K", "M"],
            "generation": {"claimed_set_key": "K M"},
            "exercises": [exercise],
            "symbols": [],
        }

    (koch_dir / "koch-exercise-20260518T130000Z.json").write_text(
        json.dumps(_record("2026-05-18T13:00:00.000Z", _exercise(1, "KM", "KM", 2)))
    )
    (koch_dir / "koch-exercise-20260518T140000Z.json").write_text(
        json.dumps(_record("2026-05-18T14:00:00.000Z", _exercise(2, "KM", "KR", 1)))
    )

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/koch-burden-profile?claimed_set_key=K%20M",
        )
        payload = json.loads(response.read())
        assert payload["version"] == "burden-profile-v1"
        assert payload["claimed_set_key"] == "K M"
        assert payload["records_used"] == 2

        symbol_inventory = payload["burdens"]["symbol_inventory"]
        assert symbol_inventory["symbol_correct_units"] == 3
        assert symbol_inventory["symbol_available_units"] == 4
        assert "symbols" in symbol_inventory

        symbols = {row["symbol"]: row for row in symbol_inventory["symbols"]}
        assert symbols["K"]["lifetime_correct"] == 2
        assert symbols["K"]["lifetime_exposures"] == 2
        assert symbols["M"]["lifetime_correct"] == 1
        assert symbols["M"]["lifetime_exposures"] == 2
        assert symbols["M"]["lifetime_substitutions"] == 1
        assert symbols["M"]["recent_substitutions"] == 1
        assert any(
            "Weakest lifetime Koch symbol M" in item for item in symbol_inventory["evidence"]
        )
    finally:
        server.close()
        await server.wait_closed()


async def test_api_koch_band_history_returns_chronological_grid(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    koch_dir = save_dir / "koch-exercise"
    koch_dir.mkdir(parents=True)

    def _record(stamp: str, run_index: int, gear: int) -> dict:
        return {
            "schema_version": "2.0",
            "mode": "koch-exercise",
            "started_at": stamp,
            "claimed_set": ["K", "M"],
            "generation": {
                "claimed_set_key": "K M",
                "run_index": run_index,
                "bands": [{"index": 1, "gear": gear}],
            },
            "exercises": [
                {
                    "index": 1,
                    "burden_band": 1,
                    "gear": gear,
                    "analysis": {
                        "version": "koch-analysis-v1",
                        "saved": True,
                        "combined_fraction": 1.0,
                        "band_state": "exact",
                    },
                }
            ],
            "symbols": [],
        }

    (koch_dir / "koch-exercise-20260518T130000Z.json").write_text(
        json.dumps(_record("2026-05-18T13:00:00.000Z", 1, 0))
    )
    (koch_dir / "koch-exercise-20260518T140000Z.json").write_text(
        json.dumps(_record("2026-05-18T14:00:00.000Z", 2, 1))
    )

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/koch-band-history?claimed_set_key=K%20M",
        )
        payload = json.loads(response.read())
        assert payload["claimed_set_key"] == "K M"
        assert payload["session_count"] == 2
        # Sessions are chronological — oldest first — so the grid renders
        # left-to-right newest-on-the-right.
        assert [s["run_index"] for s in payload["sessions"]] == [1, 2]
        # The gear change at session 2 is detected.
        assert len(payload["gear_changes"]) == 1
        assert payload["gear_changes"][0]["burden_band"] == 1
        assert payload["gear_changes"][0]["previous_gear"] == 0
        assert payload["gear_changes"][0]["current_gear"] == 1
        # Current gears come from the latest session's generation profile.
        assert payload["current_gears"] == {"1": 1}
    finally:
        server.close()
        await server.wait_closed()


async def test_api_koch_attention_response_returns_st_condition_grid(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M", "U", "R"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    koch_dir = save_dir / "koch-exercise"
    koch_dir.mkdir(parents=True)

    def _exercise(index: int, s: int, t: int, fraction: float) -> dict:
        return {
            "index": index,
            "burden_band": index,
            "gear": 3,
            "s": s,
            "t": t,
            "analysis": {
                "version": "koch-analysis-v1",
                "saved": True,
                "combined_fraction": fraction,
                "symbol_correct_units": 3 if fraction >= 1.0 else 2,
                "symbol_available_units": 3,
                "spacing_correct_units": 1 if fraction >= 1.0 else 0,
                "spacing_available_units": 1,
            },
        }

    records = []
    for minute in range(4):
        records.append(
            {
                "schema_version": "2.1",
                "mode": "koch-exercise",
                "started_at": f"2026-06-03T18:{minute:02d}:00.000Z",
                "claimed_set": ["K", "M", "U", "R"],
                "generation": {"claimed_set_key": "K M R U"},
                "exercises": [
                    _exercise(1, 5, 7, 1.0),
                    _exercise(2, 8, 9, 0.75),
                ],
                "symbols": [],
            }
        )
    for index, record in enumerate(records, start=1):
        (koch_dir / f"koch-exercise-20260603T18000{index}Z.json").write_text(json.dumps(record))

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/koch-attention-response" "?claimed_set_key=K%20M%20R%20U",
        )
        payload = json.loads(response.read())
        assert payload["version"] == "attention-response-v1"
        assert payload["claimed_set_key"] == "K M R U"
        assert payload["exercise_count"] == 8
        assert payload["conditions"][0]["st_range"] == "S5 / T7"
        assert payload["conditions"][0]["axes"]["overall"]["response"] == "helped"
        assert payload["conditions"][1]["st_range"] == "S8 / T9"
        assert payload["conditions"][1]["axes"]["overall"]["response"] == "hurt"
    finally:
        server.close()
        await server.wait_closed()


async def test_api_recognition_attention_response_returns_st_condition_grid(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M", "U", "R"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    recognition_dir = save_dir / "recognition"
    recognition_dir.mkdir(parents=True)

    def _exercise(index: int, s: int, t: int, fraction: float) -> dict:
        correct = 2 if fraction >= 1.0 else 1
        substitutions = 0 if fraction >= 1.0 else 1
        return {
            "index": index,
            "target": "K M",
            "burden_band": index,
            "gear": 1,
            "s": s,
            "t": t,
            "analysis": {
                "version": "recognition-analysis-v1",
                "saved": True,
                "has_evidence": True,
                "combined_fraction": fraction,
                "counts": {
                    "correct": correct,
                    "substitution": substitutions,
                    "caught_correct": 0,
                    "caught_substitution": 0,
                    "miss": 0,
                },
            },
        }

    records = []
    for minute in range(4):
        records.append(
            {
                "schema_version": "2.1",
                "mode": "recognition",
                "started_at": f"2026-06-03T19:{minute:02d}:00.000Z",
                "claimed_set": ["K", "M", "U", "R"],
                "generation": {"claimed_set_key": "K M R U"},
                "exercises": [
                    _exercise(1, 5, 7, 1.0),
                    _exercise(2, 8, 9, 0.5),
                ],
                "symbols": [],
            }
        )
    for index, record in enumerate(records, start=1):
        (recognition_dir / f"recognition-20260603T19000{index}Z.json").write_text(
            json.dumps(record)
        )

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/recognition-attention-response"
            "?claimed_set_key=K%20M%20R%20U",
        )
        payload = json.loads(response.read())
        assert payload["version"] == "attention-response-v1"
        assert payload["claimed_set_key"] == "K M R U"
        assert payload["exercise_count"] == 8
        assert payload["conditions"][0]["st_range"] == "S5 / T7"
        assert payload["conditions"][0]["axes"]["overall"]["response"] == "helped"
        assert payload["conditions"][1]["st_range"] == "S8 / T9"
        assert payload["conditions"][1]["axes"]["overall"]["response"] == "hurt"
    finally:
        server.close()
        await server.wait_closed()


async def test_api_koch_band_evidence_empty_when_no_records(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen, f"http://127.0.0.1:{port}/api/koch-band-evidence"
        )
        payload = json.loads(response.read())
        assert payload["claimed_set_key"] == ""
        assert payload["session_count"] == 0
        assert payload["bands"] == []
    finally:
        server.close()
        await server.wait_closed()


async def test_api_recognition_confusion_separates_committed_and_caught(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M", "U", "R"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    rec_dir = save_dir / "recognition"
    rec_dir.mkdir(parents=True)

    def _ex(committed: list[list[str]], caught: list[list[str]]) -> dict:
        return {
            "index": 1,
            "analysis": {
                "version": "recognition-analysis-v1",
                "has_evidence": True,
                "committed_confusions": committed,
                "caught_confusions": caught,
            },
        }

    record = {
        "schema_version": "2.1",
        "mode": "recognition",
        "started_at": "2026-05-29T12:00:00.000Z",
        "claimed_set": ["K", "M", "U", "R"],
        "generation": {"claimed_set_key": "K M R U"},
        "exercises": [_ex([["U", "R"]], []), _ex([], [["U", "R"]])],
        "symbols": [],
    }
    (rec_dir / "recognition-20260529T120000Z.json").write_text(json.dumps(record))

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/recognition-confusion?claimed_set_key=K%20M%20R%20U",
        )
        payload = json.loads(response.read())
        assert payload["claimed_set_key"] == "K M R U"
        assert payload["exercises_used"] == 2
        assert [
            {"target": item["target"], "typed": item["typed"], "count": item["count"]}
            for item in payload["committed_substitutions"]
        ] == [{"target": "U", "typed": "R", "count": 1}]
        assert [
            {"target": item["target"], "typed": item["typed"], "count": item["count"]}
            for item in payload["caught_substitutions"]
        ] == [{"target": "U", "typed": "R", "count": 1}]
    finally:
        server.close()
        await server.wait_closed()


async def test_api_recognition_timing_returns_target_latency_rows(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M", "U", "R"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    rec_dir = save_dir / "recognition"
    rec_dir.mkdir(parents=True)
    record = {
        "schema_version": "2.1",
        "mode": "recognition",
        "started_at": "2026-06-01T12:00:00.000Z",
        "claimed_set": ["K", "M", "U", "R"],
        "generation": {
            "claimed_set_key": "K M R U",
            "recognition": {"recognition_time_ms": 1500},
        },
        "symbols": [
            {"symbol": "R", "t_on": 0.0, "t_off": 0.4, "exercise_index": 1},
            {"symbol": "K", "t_on": 1.0, "t_off": 1.5, "exercise_index": 1},
        ],
        "exercises": [
            {
                "index": 1,
                "target": "R K",
                "answer": "RK",
                "voice_capture": [{"t": 4.0, "text": "romeo kilo", "symbols": ["R", "K"]}],
                "analysis": {
                    "has_evidence": True,
                    "combined_fraction": 1.0,
                    "committed_confusions": [],
                    "counts": {"miss": 0},
                },
            }
        ],
    }
    (rec_dir / "recognition-20260601T120000Z.json").write_text(json.dumps(record))

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/recognition-timing?claimed_set_key=K%20M%20R%20U",
        )
        payload = json.loads(response.read())
        assert payload["claimed_set_key"] == "K M R U"
        assert payload["exercises_used"] == 1
        assert payload["targets"][0]["target"] == "RK"
        assert payload["targets"][0]["median_ms"] == 2500
        assert payload["targets"][0]["late_count"] == 1
    finally:
        server.close()
        await server.wait_closed()


async def test_api_recognition_burden_profile_returns_debt_profile(tmp_path):
    config_path = _write_test_config(tmp_path, ["K", "M", "U", "R"])
    save_dir = tmp_path / "data"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
    web_root = _make_web_root(tmp_path)

    rec_dir = save_dir / "recognition"
    rec_dir.mkdir(parents=True)
    record = {
        "schema_version": "2.1",
        "mode": "recognition",
        "started_at": "2026-06-01T12:00:00.000Z",
        "claimed_set": ["K", "M", "U", "R"],
        "generation": {"claimed_set_key": "K M R U", "gear": 1},
        "exercises": [
            {
                "index": 1,
                "gear": 1,
                "analysis": {
                    "has_evidence": True,
                    "combined_fraction": 0.8,
                    "counts": {
                        "correct": 1,
                        "substitution": 1,
                        "caught_correct": 0,
                        "caught_substitution": 0,
                        "miss": 0,
                    },
                    "committed_confusions": [["U", "R"]],
                    "caught_confusions": [],
                    "slots": [
                        {"truth": "K", "outcome": "correct"},
                        {"truth": "U", "outcome": "substitution"},
                    ],
                },
                "timing_analysis": {
                    "has_evidence": True,
                    "caught_confusions": [["U", "R"]],
                },
            }
        ],
    }
    (rec_dir / "recognition-20260601T120000Z.json").write_text(json.dumps(record))

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
    )
    try:
        response = await asyncio.to_thread(
            urllib.request.urlopen,
            f"http://127.0.0.1:{port}/api/recognition-burden-profile"
            "?claimed_set_key=K%20M%20R%20U",
        )
        payload = json.loads(response.read())
        assert payload["version"] == "burden-profile-v1"
        assert payload["claimed_set_key"] == "K M R U"
        assert payload["window_size"] == 20
        assert payload["records_used"] == 1
        assert payload["burdens"]["unit_length"]["debt"] == "moderate"
        assert payload["burdens"]["confusion"]["committed"] == []
        assert payload["burdens"]["confusion"]["caught"] == [
            {"target": "U", "typed": "R", "count": 1}
        ]
        assert payload["burdens"]["signal"]["debt"] == "unknown"
    finally:
        server.close()
        await server.wait_closed()


async def test_start_action_runs_a_session(tmp_path, patched_playback):
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
            # Skip the initial claimed-symbols push.
            await asyncio.wait_for(ws.recv(), timeout=2.0)

            await ws.send(json.dumps({"action": "start"}))
            events = await _drain_until(ws, lambda e: e["type"] == "session-end", timeout=25.0)

        kinds = [e["type"] for e in events]
        assert kinds[0] == "session-start"
        assert kinds[-1] == "session-end"

        start_event = events[0]
        assert start_event["mode"] == "exercises"
        assert isinstance(start_event["seed"], int)
        assert start_event["exercise_count"] == 5
        assert len(start_event["exercises"]) == 5
        for exercise in start_event["exercises"]:
            # Every exercise opens with the fixed DE listening anchor
            # (spec §2.5); the remaining content is gated to the
            # claimed set (K, M here).
            assert exercise.startswith("DE ")
            assert all(ch in {"K", "M", "D", "E", " "} for ch in exercise)

        symbol_events = [e for e in events if e["type"] == "symbol"]
        assert len(symbol_events) > 0
        for ev in symbol_events:
            assert ev["symbol"] in {"K", "M", "D", "E"}
            assert isinstance(ev["exercise_index"], int)
            assert 1 <= ev["exercise_index"] <= 5
            assert isinstance(ev["word_index"], int)
            assert ev["word_index"] >= 1
        # Every exercise emits at least one symbol — indices cover 1..5.
        assert {e["exercise_index"] for e in symbol_events} == {1, 2, 3, 4, 5}
        # Each exercise's first word is the DE anchor: word_index 1 of
        # every exercise is exactly the D then E symbols, in that order.
        for exercise_index in range(1, 6):
            first_word = [
                ev
                for ev in symbol_events
                if ev["exercise_index"] == exercise_index and ev["word_index"] == 1
            ]
            assert [ev["symbol"] for ev in first_word[:2]] == ["D", "E"]

        # Audio thread was driven once, with the configured WPM.
        assert len(patched_playback) == 1
        _, params_used = patched_playback[0]
        assert params_used.character_speed_wpm == 25
    finally:
        server.close()
        await server.wait_closed()


async def test_start_action_writes_koch_record_to_save_directory(tmp_path, patched_playback):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "records"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
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
            await ws.send(json.dumps({"action": "start"}))
            events = await _drain_until(ws, lambda e: e["type"] == "session-end", timeout=25.0)

        record_dir = save_dir / "koch-exercise"
        files = list(record_dir.rglob("*.json"))
        assert len(files) == 1

        record = json.loads(files[0].read_text())
        assert record["mode"] == "koch-exercise"
        assert record["schema_version"] == "2.1"
        assert "duration_seconds" not in record
        assert record["claimed_set"] == ["K", "M"]
        assert isinstance(record["seed"], int)
        assert record["generation"]["profile_version"] == "koch-burden-v1"
        assert record["generation"]["claimed_set_key"] == "K M"
        # First start on a fresh connection produces a warm-up session.
        assert record["warm_up"] is True
        assert record["generation"]["candidate_count"] == 5
        assert len(record["exercises"]) == 5
        assert "answers" not in record
        assert record["exercises"][0]["played"].startswith("DE ")
        assert record["exercises"][0]["answer"] == ""
        assert record["exercises"][0]["analysis"]["saved"] is False
        symbol_events = [e for e in events if e["type"] == "symbol"]
        assert len(record["symbols"]) == len(symbol_events)
        for record_entry, event in zip(record["symbols"], symbol_events):
            for key in ("symbol", "t_on", "t_off", "exercise_index", "word_index", "word"):
                assert record_entry[key] == event[key]
        assert record["audio"]["character_speed_wpm"] == 25
    finally:
        server.close()
        await server.wait_closed()


async def test_save_koch_answers_merges_into_record(tmp_path, patched_playback):
    """End-to-end: session-end leaves answers empty; save-koch-answers
    rewrites the same file with the typed answers and acks."""
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "records"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
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
            await ws.send(json.dumps({"action": "start"}))
            await _drain_until(ws, lambda e: e["type"] == "session-end", timeout=25.0)

            answers = ["DE K", "DE MK", "DE KMK", "DE M", "DE KK"]
            await ws.send(json.dumps({"action": "save-koch-answers", "answers": answers}))
            ack = await asyncio.wait_for(ws.recv(), timeout=5.0)

        ack_event = json.loads(ack)
        assert ack_event["type"] == "koch-answers-saved"
        assert ack_event["answer_count"] == 5
        assert ack_event["exercise_count"] == 5

        record_dir = save_dir / "koch-exercise"
        files = list(record_dir.rglob("*.json"))
        assert len(files) == 1
        record = json.loads(files[0].read_text())
        assert [exercise["answer"] for exercise in record["exercises"]] == answers
        assert all(exercise["analysis"]["saved"] is True for exercise in record["exercises"])
        assert all("evidence" in exercise["analysis"] for exercise in record["exercises"])
        # Truth fields are untouched by the rewrite.
        assert len(record["symbols"]) > 0
        assert len(record["exercises"]) == 5
    finally:
        server.close()
        await server.wait_closed()


async def test_save_koch_answers_rejects_length_mismatch(tmp_path, patched_playback):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "records"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
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
            await ws.send(json.dumps({"action": "start"}))
            await _drain_until(ws, lambda e: e["type"] == "session-end", timeout=25.0)

            # Only 3 answers for 5 exercises — should be rejected.
            await ws.send(json.dumps({"action": "save-koch-answers", "answers": ["a", "b", "c"]}))
            ack = await asyncio.wait_for(ws.recv(), timeout=5.0)

        ack_event = json.loads(ack)
        assert ack_event["type"] == "error"
        assert ack_event["reason"] == "answers-length-mismatch"

        # File should still have unsaved exercise entries — the rejected
        # save must not have rewritten anything.
        record_dir = save_dir / "koch-exercise"
        files = list(record_dir.rglob("*.json"))
        assert len(files) == 1
        record = json.loads(files[0].read_text())
        assert all(exercise["answer"] == "" for exercise in record["exercises"])
        assert all(exercise["analysis"]["saved"] is False for exercise in record["exercises"])
    finally:
        server.close()
        await server.wait_closed()


async def test_save_koch_answers_without_pending_record_errors(tmp_path):
    """Save before any session has completed surfaces a clear error."""
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
            await ws.send(json.dumps({"action": "save-koch-answers", "answers": []}))
            ack = await asyncio.wait_for(ws.recv(), timeout=5.0)

        ack_event = json.loads(ack)
        assert ack_event["type"] == "error"
        assert ack_event["reason"] == "no-pending-koch-record"
    finally:
        server.close()
        await server.wait_closed()


async def test_save_koch_answers_is_one_shot_per_session(tmp_path, patched_playback):
    """A second save without an intervening session-end is rejected —
    the pending record is cleared after the first successful save."""
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "records"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
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
            await ws.send(json.dumps({"action": "start"}))
            await _drain_until(ws, lambda e: e["type"] == "session-end", timeout=25.0)

            answers = ["a", "b", "c", "d", "e"]
            await ws.send(json.dumps({"action": "save-koch-answers", "answers": answers}))
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
            assert first["type"] == "koch-answers-saved"

            await ws.send(json.dumps({"action": "save-koch-answers", "answers": answers}))
            second = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
            assert second["type"] == "error"
            assert second["reason"] == "no-pending-koch-record"
    finally:
        server.close()
        await server.wait_closed()


async def test_stop_during_start_does_not_write_koch_record(tmp_path, patched_playback):
    config_path = _write_test_config(tmp_path, ["K", "M"])
    save_dir = tmp_path / "records"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
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
            await ws.send(json.dumps({"action": "start"}))
            # Wait for session-start so a session is actually in flight.
            await _drain_until(ws, lambda e: e["type"] == "session-start", timeout=5.0)
            await ws.send(json.dumps({"action": "stop"}))
            await _drain_until(ws, lambda e: e["type"] == "session-end", timeout=5.0)

        record_dir = save_dir / "koch-exercise"
        assert not record_dir.exists() or list(record_dir.rglob("*.json")) == []
    finally:
        server.close()
        await server.wait_closed()


async def test_start_with_same_seed_replays_via_config_round_trip(tmp_path, patched_playback):
    """Two consecutive starts draw fresh seeds.

    A session record captures the seed so a future replay can reproduce
    the exact exercise list. The round trip is a session/replay concern;
    this test only asserts the seed plumbing is wired so each fresh
    session is independently replayable.
    """
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
            await asyncio.wait_for(ws.recv(), timeout=2.0)  # claimed push

            await ws.send(json.dumps({"action": "start"}))
            first = await _drain_until(ws, lambda e: e["type"] == "session-end", timeout=25.0)
            await ws.send(json.dumps({"action": "start"}))
            second = await _drain_until(ws, lambda e: e["type"] == "session-end", timeout=25.0)

        seed_a = first[0]["seed"]
        seed_b = second[0]["seed"]
        # Two consecutive sessions draw fresh seeds — overwhelmingly
        # likely to differ.
        assert seed_a != seed_b
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


async def test_start_key_input_decodes_sent_symbol_without_app_sidetone(
    tmp_path,
    patched_playback,
):
    config_path = _write_test_config_with_keyer(tmp_path)
    web_root = _make_web_root(tmp_path)

    def note_source(stop_event):
        del stop_event
        yield MidiNoteEvent(note=2, pressed=True, timestamp=1.0)
        yield MidiNoteEvent(note=2, pressed=False, timestamp=1.144)
        yield MidiNoteEvent(note=1, pressed=True, timestamp=1.192)
        yield MidiNoteEvent(note=1, pressed=False, timestamp=1.24)
        yield MidiNoteEvent(note=2, pressed=True, timestamp=1.288)
        yield MidiNoteEvent(note=2, pressed=False, timestamp=1.432)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
        key_note_source=note_source,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)  # claimed-symbols push

            await ws.send(json.dumps({"action": "start-key-input"}))
            events = await _drain_until(ws, lambda e: e["type"] == "sent-symbol", timeout=2.0)

        assert events[0]["type"] == "key-input-start"
        assert events[0]["character_wpm"] == 25
        assert events[0]["effective_wpm"] == 25
        assert events[0]["tone_frequency_hz"] == 600
        assert events[0]["dit_ms_expected"] == 48.0
        key_events = [event for event in events if event["type"] == "key-event"]
        assert [(event["kind"], event["pressed"]) for event in key_events] == [
            ("dah", True),
            ("dah", False),
            ("dit", True),
            ("dit", False),
            ("dah", True),
            ("dah", False),
        ]
        assert key_events[1]["duration_ms"] == 144.0
        assert key_events[1]["ratio_dits"] == 3.0
        assert events[-1]["symbol"] == "K"
        assert events[-1]["pattern"] == "-.-"
        assert events[-1]["leading_gap"] == "none"

        assert patched_playback == []
    finally:
        server.close()
        await server.wait_closed()


async def test_browser_key_input_decodes_sent_symbol(
    tmp_path,
    patched_playback,
):
    config_path = _write_test_config_with_keyer(tmp_path)
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

            await ws.send(
                json.dumps(
                    {
                        "action": "start-browser-key-input",
                        "input_name": "TRRS Trinkey M0",
                    }
                )
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            start_event = json.loads(raw)
            assert start_event["type"] == "key-input-start"
            assert start_event["source"] == "browser"
            assert start_event["input_name"] == "TRRS Trinkey M0"

            for event in [
                {"note": 2, "pressed": True, "timestamp": 1.0},
                {"note": 2, "pressed": False, "timestamp": 1.144},
                {"note": 1, "pressed": True, "timestamp": 1.192},
                {"note": 1, "pressed": False, "timestamp": 1.24},
                {"note": 2, "pressed": True, "timestamp": 1.288},
                {"note": 2, "pressed": False, "timestamp": 1.432},
            ]:
                await ws.send(json.dumps({"action": "key-note-event", **event}))

            events = await _drain_until(ws, lambda e: e["type"] == "sent-symbol", timeout=2.0)

        key_events = [event for event in events if event["type"] == "key-event"]
        assert [(event["kind"], event["pressed"]) for event in key_events] == [
            ("dah", True),
            ("dah", False),
            ("dit", True),
            ("dit", False),
            ("dah", True),
            ("dah", False),
        ]
        assert events[-1]["symbol"] == "K"
        assert events[-1]["pattern"] == "-.-"
        assert patched_playback == []
    finally:
        server.close()
        await server.wait_closed()


async def test_browser_key_input_reset_discards_pending_symbol(
    tmp_path,
    patched_playback,
):
    config_path = _write_test_config_with_keyer(tmp_path)
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

            await ws.send(
                json.dumps(
                    {
                        "action": "start-browser-key-input",
                        "input_name": "TRRS Trinkey M0",
                    }
                )
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            assert json.loads(raw)["type"] == "key-input-start"

            await ws.send(
                json.dumps(
                    {"action": "key-note-event", "note": 1, "pressed": True, "timestamp": 1.0}
                )
            )
            await ws.send(
                json.dumps(
                    {"action": "key-note-event", "note": 1, "pressed": False, "timestamp": 1.06}
                )
            )
            await ws.send(json.dumps({"action": "reset-key-input", "reason": "manual"}))

            events = await _drain_until(
                ws,
                lambda e: e["type"] == "key-input-reset",
                timeout=2.0,
            )
            assert [event["type"] for event in events] == [
                "key-event",
                "key-event",
                "key-input-reset",
            ]
            assert events[-1]["reason"] == "manual"

            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(ws.recv(), timeout=1.0)

        assert patched_playback == []
    finally:
        server.close()
        await server.wait_closed()


async def test_start_key_input_marks_word_gap_between_symbols(
    tmp_path,
    patched_playback,
):
    config_path = _write_test_config_with_keyer(tmp_path)
    web_root = _make_web_root(tmp_path)

    def note_source(stop_event):
        del stop_event
        # K: -.- at the configured 25 WPM test character rhythm.
        yield MidiNoteEvent(note=2, pressed=True, timestamp=1.0)
        yield MidiNoteEvent(note=2, pressed=False, timestamp=1.144)
        yield MidiNoteEvent(note=1, pressed=True, timestamp=1.192)
        yield MidiNoteEvent(note=1, pressed=False, timestamp=1.24)
        yield MidiNoteEvent(note=2, pressed=True, timestamp=1.288)
        yield MidiNoteEvent(note=2, pressed=False, timestamp=1.432)
        # Gap to M is longer than a 25 WPM word gap.
        yield MidiNoteEvent(note=2, pressed=True, timestamp=1.9)
        yield MidiNoteEvent(note=2, pressed=False, timestamp=2.044)
        yield MidiNoteEvent(note=2, pressed=True, timestamp=2.092)
        yield MidiNoteEvent(note=2, pressed=False, timestamp=2.236)

    server, port = await app.serve_app(
        port=_grab_free_port(),
        port_search_span=5,
        web_root=web_root,
        config_path=config_path,
        key_note_source=note_source,
    )
    try:
        async with ws_connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2.0)  # claimed-symbols push

            await ws.send(json.dumps({"action": "start-key-input"}))
            events = await _drain_until(
                ws,
                lambda e: e["type"] == "sent-symbol" and e["symbol"] == "M",
                timeout=2.0,
            )

        sent = [event for event in events if event["type"] == "sent-symbol"]
        assert [(event["symbol"], event["pattern"], event["leading_gap"]) for event in sent] == [
            ("K", "-.-", "none"),
            ("M", "--", "word"),
        ]
        assert patched_playback == []
    finally:
        server.close()
        await server.wait_closed()


async def test_cadence_session_writes_analyzed_record_on_close(
    tmp_path,
    patched_playback,
):
    config_path = _write_test_config_with_keyer(tmp_path)
    save_dir = tmp_path / "records"
    config_path.write_text(
        config_path.read_text() + f'\n[storage]\nsave_directory = "{save_dir}"\n'
    )
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
            await ws.send(json.dumps({"action": "request-copy-exercises"}))
            copy_event = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert copy_event["type"] == "copy-exercises"
            assert all(
                "KKK" not in exercise.replace(" ", "") and "MMM" not in exercise.replace(" ", "")
                for exercise in copy_event["exercises"]
            )

            await ws.send(json.dumps({"action": "start-browser-key-input"}))
            start_event = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert start_event["type"] == "key-input-start"

            for event in [
                {"note": 2, "pressed": True, "timestamp": 1.0},
                {"note": 2, "pressed": False, "timestamp": 1.144},
                {"note": 1, "pressed": True, "timestamp": 1.192},
                {"note": 1, "pressed": False, "timestamp": 1.24},
                {"note": 2, "pressed": True, "timestamp": 1.288},
                {"note": 2, "pressed": False, "timestamp": 1.432},
            ]:
                await ws.send(json.dumps({"action": "key-note-event", **event}))
            await _drain_until(ws, lambda e: e["type"] == "sent-symbol", timeout=2.0)
            await ws.send(json.dumps({"action": "stop-key-input"}))
            await asyncio.sleep(0)

        record_dir = save_dir / "cadence-send"
        files = list(record_dir.rglob("cadence-send-*.json"))
        assert len(files) == 1
        record = json.loads(files[0].read_text())
        assert record["mode"] == "cadence-send"
        assert record["schema_version"] == "2.1"
        assert record["generation"]["profile_version"] == "cadence-burden-v1"
        assert record["generation"]["claimed_set_key"] == "K M"
        assert record["generation"]["run_index"] == 1
        assert len(record["exercises"]) == 5
        assert record["exercises"][0]["target"] == copy_event["exercises"][0]
        assert record["exercises"][0]["analysis"]["saved"] is True
        assert "selection" not in record
        assert len(record["sent"]) == 1
        assert len(record["key_events"]) == 6
        assert any("duration_ms" in event for event in record["key_events"])
        assert patched_playback == []
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
                "tone_shape": 2,
                "receiver_bed": 2,
                "cadence_variation": 1,
                "keyer_mode": "iambic_a",
                "hh_clear_enabled": False,
                "save_directory": str(config_path.parent),
                "warm_up_timeout_minutes": 10.0,
                "say_before": True,
                "morse_count": 1,
                "recognition_time_ms": 3000,
                "say_after": True,
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
                        "tone_shape": 3,
                        "receiver_bed": 2,
                        "cadence_variation": 1,
                        "keyer_mode": "ultimatic",
                        "hh_clear_enabled": True,
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
                "tone_shape": 3,
                "receiver_bed": 2,
                "cadence_variation": 1,
                "keyer_mode": "ultimatic",
                "hh_clear_enabled": True,
                "save_directory": str(config_path.parent),
                "warm_up_timeout_minutes": 10.0,
                "say_before": True,
                "morse_count": 1,
                "recognition_time_ms": 3000,
                "say_after": True,
            }

        from copy_653.config import (
            load_audio_parameters,
            load_developer_settings,
            load_keyer_settings,
        )

        params = load_audio_parameters(config_path)
        assert params.character_speed_wpm == 20
        assert params.effective_speed_wpm == 10
        assert params.envelope_ramp_seconds == 0.007
        assert params.receiver_bed == 2
        assert params.cadence_variation == 1
        keyer = load_keyer_settings(config_path)
        assert keyer.keyer_mode == "ultimatic"
        developer = load_developer_settings(config_path)
        assert developer.hh_clear_enabled is True
        data = tomllib.loads(config_path.read_text())
        assert data["midi"]["key"] == {
            "input_name": "TRRS Trinkey",
            "dit_note": 1,
            "dah_note": 2,
            "straight_note": 0,
            "keyer_mode": "ultimatic",
        }
        assert data["developer"] == {"hh_clear_enabled": True}
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


async def test_set_audio_settings_rejects_invalid_texture(tmp_path, patched_playback):
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
                        "tone_shape": 11,
                    }
                )
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)
            assert event["type"] == "error"
            assert event["reason"] == "invalid-audio-settings"
            assert "tone_shape" in event["detail"]
    finally:
        server.close()
        await server.wait_closed()


async def test_play_test_message_uses_payload_settings(tmp_path, patched_playback):
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
                        "action": "play-test-message",
                        "character_wpm": 20,
                        "effective_wpm": 10,
                        "tone_shape": 3,
                        "receiver_bed": 4,
                        "cadence_variation": 2,
                    }
                )
            )
            events = await _drain_until(
                ws,
                lambda e: e["type"] == "test-message-end",
                timeout=5.0,
            )

        assert events == [{"type": "test-message-start"}, {"type": "test-message-end"}]
        assert len(patched_playback) == 1
        samples, params = patched_playback[0]
        assert samples.size > 0
        assert params.character_speed_wpm == 20
        assert params.effective_speed_wpm == 10
        assert params.envelope_ramp_seconds == 0.007
        assert params.receiver_bed == 4
        assert params.cadence_variation == 2
    finally:
        server.close()
        await server.wait_closed()


async def test_save_test_message_returns_chunked_wav(tmp_path):
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
                        "action": "save-test-message",
                        "character_wpm": 20,
                        "effective_wpm": 10,
                        "tone_shape": 3,
                        "receiver_bed": 4,
                        "cadence_variation": 2,
                    }
                )
            )
            events = await _drain_until(
                ws,
                lambda e: e["type"] == "test-message-wav-end",
                timeout=5.0,
            )

        assert events[0]["type"] == "test-message-wav-start"
        assert events[0]["filename"] == "copy-653-marconi-test-message.wav"
        chunks = [event["data"] for event in events if event["type"] == "test-message-wav-chunk"]
        assert chunks
        body = b"".join(base64.b64decode(chunk) for chunk in chunks)
        assert len(body) == events[0]["byte_length"]

        with wave.open(io.BytesIO(body), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2
            assert wav.getframerate() == 48_000
            assert wav.getnframes() > 48_000 * 4
    finally:
        server.close()
        await server.wait_closed()


async def test_save_test_message_rejects_invalid_settings(tmp_path):
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
                        "action": "save-test-message",
                        "character_wpm": 10,
                        "effective_wpm": 20,
                        "tone_shape": 3,
                        "receiver_bed": 4,
                        "cadence_variation": 2,
                    }
                )
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            event = json.loads(raw)

        assert event["type"] == "error"
        assert event["reason"] == "invalid-test-message-settings"
        assert "cannot exceed" in event["detail"]
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
