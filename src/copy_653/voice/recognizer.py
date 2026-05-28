"""Vosk recogniser wrapper.

Wraps :class:`vosk.KaldiRecognizer` with the project's grammar
(:func:`copy_653.voice.grammar.build_grammar`) and exposes a small
``feed_pcm(bytes) → list[VoiceEvent]`` surface. The vosk import is
*lazy* so this module can be imported even when the optional
``voice`` extra is not installed; users who never open the
``/voice/ws`` endpoint pay no import cost.

Wire shape: each WS connection owns one :class:`Recognizer`. Binary
frames are Int16 little-endian PCM at 16 kHz mono. :func:`feed_pcm`
returns the events produced by that chunk — zero or more partials
and an optional final.

Honesty contract (spec §1.5):

* Missing ``vosk`` dependency → :class:`VoiceUnavailableError` at
  :meth:`Recognizer.from_settings` time, never silently no-op'd.
* ``[voice]`` table absent (``settings.model_path is None``) →
  :class:`VoiceUnavailableError`; caller is responsible for the
  user-facing "voice not configured" surface.
* Resolved model path doesn't exist → :class:`VoiceUnavailableError`
  naming the path.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from copy_653.config import VoiceSettings
from copy_653.voice.grammar import UNKNOWN_TOKEN, build_grammar, resolve_symbols
from copy_653.voice.lexicon import Lexicon, load_lexicon

SAMPLE_RATE_HZ = 16_000


class VoiceUnavailableError(RuntimeError):
    """Raised when the speech recogniser cannot be constructed.

    Causes include: the ``voice`` extra not installed (``vosk`` import
    fails), ``[voice]`` config absent, model path missing on disk.
    """


@dataclass(frozen=True, slots=True)
class PartialResult:
    """An interim transcript that may still change.

    ``symbols`` is the ordered list of CW symbols the tokeniser
    extracted from ``text`` so far — empty when the partial contains
    only off-vocabulary words.
    """

    text: str
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FinalResult:
    """A committed transcript with the resolved CW symbols, in order.

    Multi-symbol finals are produced when the user speaks several
    grammar phrases in one breath (e.g. ``"uniform kilo mike"`` →
    ``("U","K","M")``). Single-phrase utterances yield a one-element
    tuple; off-vocabulary utterances yield an empty tuple.
    """

    text: str
    symbols: tuple[str, ...]


VoiceEvent = PartialResult | FinalResult


def _import_vosk() -> Any:
    """Import :mod:`vosk` lazily and translate ImportError into our domain error."""
    try:
        return importlib.import_module("vosk")
    except ImportError as err:  # pragma: no cover — exercised in tests via monkeypatch
        raise VoiceUnavailableError(
            "vosk is not installed; install the 'voice' extra: " '`pip install -e ".[voice]"`'
        ) from err


class Recognizer:
    """One Vosk recogniser per WS connection.

    Construct via :meth:`from_settings`. Feed Int16 PCM via
    :meth:`feed_pcm`; consume :class:`VoiceEvent`s from the returned
    list. Call :meth:`reset` to flush in-flight decoder state without
    discarding the loaded model.
    """

    def __init__(self, *, lexicon: Lexicon, model: Any, kaldi: Any, vosk_module: Any) -> None:
        self._lexicon = lexicon
        self._model = model
        self._kaldi = kaldi
        self._vosk = vosk_module

    @classmethod
    def from_settings(
        cls,
        settings: VoiceSettings,
        *,
        lexicon: Lexicon | None = None,
        vosk_module: Any | None = None,
    ) -> "Recognizer":
        """Build a recogniser for ``settings``.

        ``lexicon`` and ``vosk_module`` are injectable for tests; in
        production they default to the bundled English lexicon and the
        real :mod:`vosk` package.
        """
        if settings.model_path is None:
            raise VoiceUnavailableError(
                "[voice].model_path is not configured; "
                "voice input is disabled until a model path is set"
            )

        resolved = settings.resolved_model_path()
        if resolved is None or not Path(resolved).is_dir():
            raise VoiceUnavailableError(f"voice model directory does not exist: {resolved}")

        vosk = vosk_module if vosk_module is not None else _import_vosk()
        lex = lexicon if lexicon is not None else load_lexicon(settings.language)

        grammar_json = json.dumps(build_grammar(lex))
        try:
            model = vosk.Model(str(resolved))
            kaldi = vosk.KaldiRecognizer(model, SAMPLE_RATE_HZ, grammar_json)
        except Exception as err:
            raise VoiceUnavailableError(f"failed to load Vosk model at {resolved}: {err}") from err

        return cls(lexicon=lex, model=model, kaldi=kaldi, vosk_module=vosk)

    def feed_pcm(self, frame: bytes) -> list[VoiceEvent]:
        """Feed one PCM chunk; return any events produced by it.

        Returns an empty list if Vosk produced neither a partial nor a
        final for this chunk. A non-trivial chunk usually produces one
        :class:`PartialResult`; a chunk that crosses a silence boundary
        produces a :class:`FinalResult`. Either event carries the full
        ordered list of symbols its text decoded to (see
        :func:`copy_653.voice.grammar.resolve_symbols`).
        """
        events: list[VoiceEvent] = []
        if self._kaldi.AcceptWaveform(frame):
            text = _normalise(json.loads(self._kaldi.Result()).get("text"))
            if text and text != UNKNOWN_TOKEN:
                symbols = tuple(resolve_symbols(self._lexicon, text))
                events.append(FinalResult(text=text, symbols=symbols))
        else:
            partial = _normalise(json.loads(self._kaldi.PartialResult()).get("partial"))
            if partial:
                symbols = tuple(resolve_symbols(self._lexicon, partial))
                events.append(PartialResult(text=partial, symbols=symbols))
        return events

    def reset(self) -> None:
        """Flush decoder state without rebuilding the model.

        Cheap: rebuilds only the :class:`KaldiRecognizer`, not the
        ~50 MB ``Model``. Reuses the vosk module reference captured at
        construction.
        """
        grammar_json = json.dumps(build_grammar(self._lexicon))
        self._kaldi = self._vosk.KaldiRecognizer(self._model, SAMPLE_RATE_HZ, grammar_json)


def _normalise(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()
