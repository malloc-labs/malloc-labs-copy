"""Voice input for the Symbol Recognition page (spec §2.6).

Voice is one input modality for the recognition page — alongside MIDI key
input and manual entry. This sub-package owns the lexicon (symbol →
spoken phrases), the grammar (the phrase list fed to a speech-recogniser
like Vosk), and — in later phases — the recogniser wrapper itself.

The sub-package does NOT own the existing :class:`RecognitionSettings`
config table (spec §2.6 training-mode knobs); those remain in
:mod:`copy_653.config`. Voice-specific config lives under ``[voice]``.

Phase 1 (this commit) ships data and validation only — no Vosk
dependency at import time, no audio handling. The lexicon files under
``src/copy_653/assets/lexicon/`` are the single source of truth for
what spoken phrases map to which CW symbols; the grammar is a derived
view of the lexicon suitable for handing to
:class:`vosk.KaldiRecognizer`.
"""

from copy_653.voice.grammar import build_grammar, resolve_symbols
from copy_653.voice.lexicon import Lexicon, LexiconError, load_lexicon
from copy_653.voice.recognizer import (
    SAMPLE_RATE_HZ,
    FinalResult,
    PartialResult,
    Recognizer,
    VoiceEvent,
    VoiceUnavailableError,
)

__all__ = [
    "FinalResult",
    "Lexicon",
    "LexiconError",
    "PartialResult",
    "Recognizer",
    "SAMPLE_RATE_HZ",
    "VoiceEvent",
    "VoiceUnavailableError",
    "build_grammar",
    "load_lexicon",
    "resolve_symbols",
]
