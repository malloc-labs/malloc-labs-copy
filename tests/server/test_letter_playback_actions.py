from __future__ import annotations

import json
from pathlib import Path

from copy_653.server.letter_playback_actions import _run_morse_repeat


class RecordingWebSocket:
    def __init__(self):
        self.events: list[dict] = []

    async def send(self, payload: str) -> None:
        self.events.append(json.loads(payload))


async def test_morse_repeat_playback_failure_emits_error_without_reraising(
    tmp_path: Path,
    monkeypatch,
):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[audio]\ncharacter_speed_wpm = 20\neffective_speed_wpm = 20\n")

    async def _fail_playback(*_args, **_kwargs):
        raise RuntimeError("PortAudio route failed")

    monkeypatch.setattr(
        "copy_653.server.letter_playback_actions.play_morse_sequence",
        _fail_playback,
    )
    ws = RecordingWebSocket()

    await _run_morse_repeat(ws, "K", 3, config_path)

    assert ws.events == [
        {"type": "morse-repeat-start", "symbol": "K", "repeats": 3},
        {
            "type": "error",
            "reason": "morse-repeat-failed",
            "symbol": "K",
            "detail": "PortAudio route failed",
        },
    ]
