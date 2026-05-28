"""Grammar construction from a validated :class:`Lexicon`.

Vosk's :class:`KaldiRecognizer` accepts a JSON list of allowed
phrases as its grammar. Anything outside the grammar collapses to
``[unk]`` server-side and is dropped — this constrains the decoder
itself, not the post-hoc string match.

This module is a thin view layer over :mod:`copy_653.voice.lexicon`:

* :func:`build_grammar` returns the phrase list (plus ``[unk]``)
  ready to hand to ``KaldiRecognizer``.
* :func:`resolve_symbol` is the reverse lookup the recogniser
  callback uses to turn a recognised phrase back into a CW symbol.

Phase 1 does not import Vosk — :func:`build_grammar` returns a plain
list. Phase 2 will hand the same list to ``KaldiRecognizer`` via
``json.dumps``.
"""

from __future__ import annotations

from copy_653.voice.lexicon import Lexicon

UNKNOWN_TOKEN = "[unk]"


def build_grammar(lexicon: Lexicon) -> list[str]:
    """Return the phrase list for ``KaldiRecognizer``.

    The list is sorted (stable across runs) and contains every
    unique spoken phrase in ``lexicon`` plus the ``[unk]`` sentinel
    that lets Vosk collapse off-vocabulary speech instead of
    forcing a match.
    """
    phrases = list(lexicon.phrases())
    if UNKNOWN_TOKEN not in phrases:
        phrases.append(UNKNOWN_TOKEN)
    return phrases


def resolve_symbol(lexicon: Lexicon, phrase: str) -> str | None:
    """Resolve a recognised phrase to its CW symbol.

    Returns ``None`` for ``[unk]``, the empty string, or any phrase
    that isn't in the lexicon. The lexicon's own uniqueness
    invariant (enforced at load time) guarantees the lookup is
    unambiguous.
    """
    if not phrase or phrase == UNKNOWN_TOKEN:
        return None
    return lexicon.symbol_for(phrase.strip().lower())
