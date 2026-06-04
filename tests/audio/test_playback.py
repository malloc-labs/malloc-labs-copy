from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from copy_653.audio.playback import play_samples, resolve_output_device


class FakeSoundDevice:
    def __init__(self):
        self.play_calls = []
        self.stop_calls = 0

    def query_devices(self):
        return [
            {
                "index": 2,
                "name": "Mac mini Speakers",
                "hostapi": 0,
                "max_output_channels": 2,
            },
            {
                "index": 7,
                "name": "USB Headphones",
                "hostapi": 0,
                "max_output_channels": 2,
            },
            {
                "index": 8,
                "name": "Input Only",
                "hostapi": 0,
                "max_output_channels": 0,
            },
        ]

    def query_hostapis(self, _hostapi):
        return {"name": "Core Audio"}

    def play(self, samples, *, samplerate, device, blocking):
        self.play_calls.append(
            {
                "size": samples.size,
                "samplerate": samplerate,
                "device": device,
                "blocking": blocking,
            }
        )

    def stop(self):
        self.stop_calls += 1


def test_resolve_output_device_accepts_full_settings_label():
    sd = FakeSoundDevice()

    assert resolve_output_device(sd, "USB Headphones, Core Audio") == 7


def test_resolve_output_device_falls_back_to_sounddevice_for_unknown_name():
    sd = FakeSoundDevice()

    assert resolve_output_device(sd, "Missing Device") == "Missing Device"


def test_play_samples_retries_default_when_saved_device_is_stale(monkeypatch):
    sd = FakeSoundDevice()

    def _play(samples, *, samplerate, device, blocking):
        sd.play_calls.append(
            {
                "size": samples.size,
                "samplerate": samplerate,
                "device": device,
                "blocking": blocking,
            }
        )
        if len(sd.play_calls) == 1:
            raise RuntimeError("PortAudio device went stale")

    sd.play = _play
    monkeypatch.setitem(sys.modules, "sounddevice", sd)

    play_samples(np.zeros(4, dtype=np.float32), 44_100, "USB Headphones, Core Audio")

    assert [call["device"] for call in sd.play_calls] == [7, None]
    assert sd.stop_calls == 1


def test_play_samples_does_not_retry_default_failures(monkeypatch):
    sd = SimpleNamespace()
    sd.play = Mock(side_effect=RuntimeError("default failed"))
    monkeypatch.setitem(sys.modules, "sounddevice", sd)

    with pytest.raises(RuntimeError, match="default failed"):
        play_samples(np.zeros(4, dtype=np.float32), 44_100, None)

    assert sd.play.call_count == 1
