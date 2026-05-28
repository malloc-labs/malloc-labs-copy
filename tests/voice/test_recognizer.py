"""Tests for copy_653.voice.recognizer.

A fake ``vosk`` module is injected so these tests run without the
real Vosk dependency or any model on disk.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Iterable

import pytest

from copy_653.config import VoiceSettings
from copy_653.voice.lexicon import load_lexicon
from copy_653.voice.recognizer import (
    FinalResult,
    PartialResult,
    Recognizer,
    VoiceUnavailableError,
)

# ---------- fake vosk shim ---------------------------------------------


class _FakeKaldiRecognizer:
    """Reads scripted ``(is_final, text)`` tuples and replays them in order."""

    def __init__(self, model: Any, sample_rate: int, grammar: str) -> None:
        self.model = model
        self.sample_rate = sample_rate
        self.grammar = json.loads(grammar)
        self.script: list[tuple[bool, str]] = []
        self.feed_calls = 0

    def AcceptWaveform(self, frame: bytes) -> bool:  # noqa: N802 — Vosk's casing
        self.feed_calls += 1
        if not self.script:
            return False
        is_final, _text = self.script[0]
        # Consume the entry if it's a final; partials stay until cleared.
        if is_final:
            self.script.pop(0)
        return is_final

    def Result(self) -> str:  # noqa: N802
        # The last consumed entry was a final.
        text = self._last_consumed_text
        return json.dumps({"text": text})

    def PartialResult(self) -> str:  # noqa: N802
        if not self.script:
            return json.dumps({"partial": ""})
        is_final, text = self.script[0]
        assert not is_final
        # Drop the partial entry — one peek per feed call.
        self.script.pop(0)
        return json.dumps({"partial": text})

    @property
    def _last_consumed_text(self) -> str:
        # Bound to the most recent final the test scripted.
        return self.__dict__.setdefault("_pending_final", "")


class _FakeVosk:
    Model = staticmethod(lambda path: ("model", path))
    KaldiRecognizer = _FakeKaldiRecognizer


def _build(script: Iterable[tuple[bool, str]]) -> Recognizer:
    """Construct a Recognizer wired to the fake vosk module and a script."""
    lex = load_lexicon("en")
    # Bypass the from_settings model-path-exists check by going through
    # the constructor directly with a fake KaldiRecognizer.
    grammar = json.dumps(["alpha", "bravo", "x ray", "five", "[unk]"])
    fake_kaldi = _FakeKaldiRecognizer(model=("fake",), sample_rate=16_000, grammar=grammar)
    fake_kaldi.script = list(script)
    return Recognizer(
        lexicon=lex,
        model=("fake",),
        kaldi=fake_kaldi,
        vosk_module=_FakeVosk,
    )


# ---------- from_settings error surfaces -------------------------------


def test_from_settings_raises_when_model_path_none():
    with pytest.raises(VoiceUnavailableError, match="not configured"):
        Recognizer.from_settings(VoiceSettings(model_path=None))


def test_from_settings_raises_when_model_dir_missing(tmp_path):
    settings = VoiceSettings(model_path=str(tmp_path / "missing-model"))
    with pytest.raises(VoiceUnavailableError, match="does not exist"):
        Recognizer.from_settings(settings)


def test_from_settings_raises_when_vosk_import_fails(monkeypatch, tmp_path):
    model_dir = tmp_path / "fake-model"
    model_dir.mkdir()
    settings = VoiceSettings(model_path=str(model_dir))

    monkeypatch.setitem(sys.modules, "vosk", None)

    def failing_import(name: str) -> Any:
        if name == "vosk":
            raise ImportError("not installed")
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("copy_653.voice.recognizer.importlib.import_module", failing_import)

    with pytest.raises(VoiceUnavailableError, match="vosk is not installed"):
        Recognizer.from_settings(settings)


def test_from_settings_uses_injected_vosk_module(tmp_path):
    model_dir = tmp_path / "fake-model"
    model_dir.mkdir()
    settings = VoiceSettings(model_path=str(model_dir))
    rec = Recognizer.from_settings(settings, vosk_module=_FakeVosk)
    assert isinstance(rec, Recognizer)


# ---------- feed_pcm event emission ------------------------------------


def test_feed_pcm_emits_partial_for_in_progress_decode():
    rec = _build([(False, "al")])
    events = rec.feed_pcm(b"\x00\x00" * 256)
    assert len(events) == 1
    assert isinstance(events[0], PartialResult)
    assert events[0].text == "al"
    assert events[0].symbol is None  # "al" isn't a complete lexicon phrase


def test_feed_pcm_emits_final_with_resolved_symbol():
    rec = _build([(True, "alpha")])
    # Pre-stash the final text the fake will report.
    rec._kaldi.__dict__["_pending_final"] = "alpha"  # type: ignore[attr-defined]
    events = rec.feed_pcm(b"\x00\x00" * 256)
    assert len(events) == 1
    final = events[0]
    assert isinstance(final, FinalResult)
    assert final.text == "alpha"
    assert final.symbol == "A"


def test_feed_pcm_drops_unk_finals():
    rec = _build([(True, "[unk]")])
    rec._kaldi.__dict__["_pending_final"] = "[unk]"  # type: ignore[attr-defined]
    assert rec.feed_pcm(b"\x00\x00" * 256) == []


def test_feed_pcm_drops_empty_partials():
    rec = _build([(False, "")])
    assert rec.feed_pcm(b"\x00\x00" * 256) == []


def test_feed_pcm_resolves_multiword_phrases():
    rec = _build([(True, "x ray")])
    rec._kaldi.__dict__["_pending_final"] = "x ray"  # type: ignore[attr-defined]
    events = rec.feed_pcm(b"\x00\x00" * 256)
    assert isinstance(events[0], FinalResult)
    assert events[0].symbol == "X"


# ---------- reset ------------------------------------------------------


def test_reset_replaces_kaldi_recognizer():
    rec = _build([(False, "al")])
    original = rec._kaldi  # type: ignore[attr-defined]
    rec.reset()
    assert rec._kaldi is not original  # type: ignore[attr-defined]
