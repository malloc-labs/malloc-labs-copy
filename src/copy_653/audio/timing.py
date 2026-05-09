"""WPM ↔ second conversions, including Farnsworth spacing.

CW timing is conventionally measured in *dit-units*. A "word" is, by
convention, the string PARIS, which works out to exactly 50 dit-units
when transmitted with standard spacing. From that, one dit at a given
WPM is::

    dit_seconds = 60 / (WPM × 50) = 1.2 / WPM

Farnsworth spacing (Russ Farnsworth, c. 1959) keeps the *element*
timing fast — so the brain learns shapes rather than counts dits —
while inserting extra silence between characters and between words to
lower the *effective* speed.

This module provides:

- :func:`dit_seconds`, :func:`dah_seconds`, :func:`inter_element_seconds`
  — element-level timing at the character speed.
- :func:`inter_character_seconds`, :func:`inter_word_seconds`
  — gaps that respect Farnsworth when present.
"""

from __future__ import annotations

from copy_653.audio.parameters import AudioParameters

# A standard PARIS word breaks down as:
#   - 31 dit-units of "intra-character" time (dits/dahs and inter-element
#     spaces within characters)
#   - 12 dit-units of inter-character spacing (4 spaces × 3 dits each)
#   - 7 dit-units of inter-word spacing (1 space × 7 dits)
# Total 50 dit-units.
#
# Derivation, for the curious:
#   P = .--.   = 1+1+3+1+3+1+1 = 11 dits
#   A = .-     = 1+1+3         = 5 dits
#   R = .-.    = 1+1+3+1+1     = 7 dits
#   I = ..     = 1+1+1         = 3 dits
#   S = ...    = 1+1+1+1+1     = 5 dits
#   Sum of intra-char       = 31 dits
#   Inter-char spaces (4×3) = 12 dits
#   Inter-word space  (1×7) =  7 dits
#   Grand total             = 50 dits
_PARIS_INTRA_DITS = 31
_PARIS_INTERCHAR_DITS = 12
_PARIS_INTERWORD_DITS = 7
_PARIS_TOTAL_SPACE_DITS = _PARIS_INTERCHAR_DITS + _PARIS_INTERWORD_DITS  # 19


def dit_seconds(character_speed_wpm: int) -> float:
    """Length of one dit at the given character speed, in seconds.

    PARIS = 50 dit-units = 1 word; therefore at WPM W::

        dit = 60s / (W × 50) = 1.2 / W
    """
    return 1.2 / character_speed_wpm


def dah_seconds(character_speed_wpm: int) -> float:
    """A dah is exactly 3 dits long."""
    return 3 * dit_seconds(character_speed_wpm)


def inter_element_seconds(character_speed_wpm: int) -> float:
    """The silence between elements within a character is 1 dit long."""
    return dit_seconds(character_speed_wpm)


def inter_character_seconds(params: AudioParameters) -> float:
    """Silence between characters, respecting Farnsworth spacing.

    With no Farnsworth (effective == character speed), this is the
    standard 3 dits. With Farnsworth, the per-dit space duration is
    stretched so the whole PARIS-equivalent word lasts the configured
    effective duration.
    """
    return 3 * _space_dit_seconds(params)


def inter_word_seconds(params: AudioParameters) -> float:
    """Silence between words, respecting Farnsworth spacing.

    With no Farnsworth, this is the standard 7 dits. With Farnsworth,
    the per-dit space duration is stretched along with inter-character
    space.
    """
    return 7 * _space_dit_seconds(params)


def _space_dit_seconds(params: AudioParameters) -> float:
    """Effective duration of one dit-unit of *space*, with Farnsworth.

    Without Farnsworth this is just ``dit_seconds(character_speed_wpm)``.
    With Farnsworth, the 19 dit-units of space within PARIS are
    stretched so that the whole word lasts ``60 / effective_speed_wpm``
    seconds.
    """
    if params.effective_speed_wpm == params.character_speed_wpm:
        return dit_seconds(params.character_speed_wpm)

    intra_seconds = _PARIS_INTRA_DITS * dit_seconds(params.character_speed_wpm)
    target_word_seconds = 60.0 / params.effective_speed_wpm
    space_total_seconds = target_word_seconds - intra_seconds

    if space_total_seconds <= 0:
        # Defensive fallback: if effective_speed_wpm somehow exceeds
        # character_speed_wpm (rejected by AudioParameters validation,
        # but guard anyway), use standard spacing.
        return dit_seconds(params.character_speed_wpm)

    return space_total_seconds / _PARIS_TOTAL_SPACE_DITS
