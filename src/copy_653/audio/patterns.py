"""CW (International Morse Code) symbol patterns and Koch curriculum.

Each symbol maps to a string of '.' (dit) and '-' (dah). The patterns
are International Morse Code per ITU-R M.1677-1.

For v0, only the Koch first pair (K, M) is exposed via
:data:`KOCH_FIRST_PAIR`; the rest of the alphabet and digits are
included for future phases. Per philosophy.md §3.5 and §5, only
symbols the learner has claimed competence in may appear in any
stream — the symbol-set gating mechanism lives elsewhere; this module
is just the lookup table and the curriculum hint.

The Koch curriculum (:data:`KOCH_ORDER`) is a *hint*, not a contract:
the engine may suggest "Koch's next" via :func:`next_koch_after`, but
the learner is the authority on what to claim (philosophy §3.7). A
learner free-choosing Z first is a supported workflow.
"""

from __future__ import annotations

from typing import Iterable

# International Morse Code, per ITU-R M.1677-1.
PATTERNS: dict[str, str] = {
    # Letters
    "A": ".-",
    "B": "-...",
    "C": "-.-.",
    "D": "-..",
    "E": ".",
    "F": "..-.",
    "G": "--.",
    "H": "....",
    "I": "..",
    "J": ".---",
    "K": "-.-",
    "L": ".-..",
    "M": "--",
    "N": "-.",
    "O": "---",
    "P": ".--.",
    "Q": "--.-",
    "R": ".-.",
    "S": "...",
    "T": "-",
    "U": "..-",
    "V": "...-",
    "W": ".--",
    "X": "-..-",
    "Y": "-.--",
    "Z": "--..",
    # Digits
    "0": "-----",
    "1": ".----",
    "2": "..---",
    "3": "...--",
    "4": "....-",
    "5": ".....",
    "6": "-....",
    "7": "--...",
    "8": "---..",
    "9": "----.",
    # Punctuation and prosigns (ITU-R M.1677-1)
    ".": ".-.-.-",  # Full stop
    ",": "--..--",  # Comma
    "?": "..--..",  # Question mark
    "/": "-..-.",   # Fraction bar / DN
    "=": "-...-",   # Double dash / BT prosign
}


# Koch's canonical learning order (Ludwig Koch, 1935). Each symbol
# maximises shape contrast against everything claimed so far — K and
# M open the field with dah-dit-dah vs all-dahs; U is third because
# its leading dits force the ear to notice that streams can *open*
# without a dah. Punctuation and prosigns are interleaved at their
# canonical positions per the original Koch curriculum.
# A test asserts every element of KOCH_ORDER is in PATTERNS.
KOCH_ORDER: tuple[str, ...] = (
    "K", "M", "U", "R", "E", "S", "N", "A", "P", "T",
    "L", "W", "I", ".", "J", "Z", "=", "F", "O", "Y",
    ",", "V", "G", "5", "/", "Q", "9", "2", "H", "3",
    "8", "B", "?", "4", "7", "C", "1", "D", "6", "0", "X",
)  # fmt: skip


# v0 starting symbol set per docs/specification.md §2.5.
KOCH_FIRST_PAIR: tuple[str, ...] = KOCH_ORDER[:2]


def pattern_for(symbol: str) -> str:
    """Return the CW pattern for a single symbol.

    Symbol matching is case-insensitive ('k' and 'K' both yield '-.-').
    Raises :class:`KeyError` if the symbol has no defined pattern.
    """
    return PATTERNS[symbol.upper()]


def next_koch_after(claimed: Iterable[str]) -> str | None:
    """The next symbol Koch's curriculum would suggest, given ``claimed``.

    Walks :data:`KOCH_ORDER` and returns the first element that is not
    already in ``claimed``. Returns ``None`` if the learner has
    claimed every symbol Koch covers.

    This is a *suggestion*, not a gate (philosophy §3.7). A caller is
    free to ignore it and surface every unclaimed letter for hand
    selection instead.
    """
    claimed_set = {s.upper() for s in claimed}
    for symbol in KOCH_ORDER:
        if symbol not in claimed_set:
            return symbol
    return None
