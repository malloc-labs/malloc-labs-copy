"""CW (International Morse Code) symbol patterns.

Each symbol maps to a string of '.' (dit) and '-' (dah). The patterns
are International Morse Code per ITU-R M.1677-1.

For v0, only the Koch first pair (K, M) is exposed via
:data:`KOCH_FIRST_PAIR`; the rest of the alphabet and digits are
included for future phases. Per philosophy.md §3.5 and §5, only
symbols the learner has claimed competence in may appear in any
stream — the symbol-set gating mechanism lives elsewhere; this module
is just the lookup table.
"""

from __future__ import annotations

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
}


# v0 starting symbol set per docs/specification.md §2.5.
KOCH_FIRST_PAIR: tuple[str, ...] = ("K", "M")


def pattern_for(symbol: str) -> str:
    """Return the CW pattern for a single symbol.

    Symbol matching is case-insensitive ('k' and 'K' both yield '-.-').
    Raises :class:`KeyError` if the symbol has no defined pattern.
    """
    return PATTERNS[symbol.upper()]
