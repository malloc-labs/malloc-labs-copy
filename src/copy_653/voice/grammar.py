"""Grammar construction and tokenisation from a validated :class:`Lexicon`.

Vosk's :class:`KaldiRecognizer` accepts a JSON list of allowed
phrases as its grammar. Anything outside the grammar collapses to
``[unk]`` server-side and is dropped — this constrains the decoder
itself, not the post-hoc string match.

This module is a thin view layer over :mod:`copy_653.voice.lexicon`:

* :func:`build_grammar` returns the phrase list (plus ``[unk]``)
  ready to hand to ``KaldiRecognizer``.
* :func:`resolve_symbols` tokenises a recognised utterance into the
  ordered list of CW symbols it represents. Single-phrase
  utterances yield a one-element list; batched utterances like
  ``"uniform kilo mike uniform mike"`` yield ``["U","K","M","U","M"]``.

The tokeniser walks the text left-to-right and prefers the
**longest** lexicon phrase that matches at the current position
(e.g. ``"x ray"`` and ``"question mark"`` win against their
single-word substrings). Words that don't match any phrase are
silently skipped — the grammar restriction at the recogniser
already makes unknown words rare, and a clean output list is
easier for downstream consumers to handle.
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


def resolve_symbols(lexicon: Lexicon, text: str) -> list[str]:
    """Tokenise ``text`` into an ordered list of CW symbols.

    Walks ``text.split()`` left-to-right, preferring the longest
    available lexicon phrase at each position. Unknown words are
    silently skipped (see the module docstring for the rationale).

    Returns an empty list for empty / whitespace-only / ``[unk]``
    input. Always returns a new list; the caller may mutate it.
    """
    if not text:
        return []
    cleaned = text.strip().lower()
    if not cleaned or cleaned == UNKNOWN_TOKEN:
        return []

    # Precompute (phrase_words_tuple, symbol) pairs sorted by phrase
    # word count descending so multi-word phrases match first.
    indexed: list[tuple[tuple[str, ...], str]] = []
    for symbol, phrases in lexicon.entries.items():
        for phrase in phrases:
            indexed.append((tuple(phrase.split()), symbol))
    indexed.sort(key=lambda pair: -len(pair[0]))

    words = cleaned.split()
    out: list[str] = []
    i = 0
    while i < len(words):
        matched = False
        for phrase_words, symbol in indexed:
            n = len(phrase_words)
            if tuple(words[i : i + n]) == phrase_words:
                out.append(symbol)
                i += n
                matched = True
                break
        if not matched:
            i += 1
    return out
