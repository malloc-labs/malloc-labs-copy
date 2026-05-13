"""Decode already-formed key elements into Morse symbols.

The reference TRRS Trinkey firmware can emit USB MIDI notes for formed
dit/dah elements. This module deliberately starts after that hardware
keyer boundary: iambic mode handling and raw paddle state are firmware
concerns for now. Copy receives timed elements, groups them into a
pattern, and maps that pattern to a symbol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from copy_653.audio.patterns import PATTERNS

ElementKind = Literal["dit", "dah"]
LeadingGap = Literal["none", "character", "word"]

_ELEMENT_TO_MARK: dict[ElementKind, str] = {"dit": ".", "dah": "-"}
_PATTERN_TO_SYMBOL = {pattern: symbol for symbol, pattern in PATTERNS.items()}
_TIMING_EPSILON_SECONDS = 1e-9


@dataclass(frozen=True, slots=True)
class KeyElement:
    """One already-formed key element with measured start/end times."""

    kind: ElementKind
    started_at: float
    ended_at: float


@dataclass(frozen=True, slots=True)
class DecodedSymbol:
    """A completed Morse pattern and its decoded symbol, if known."""

    pattern: str
    symbol: str | None
    started_at: float
    ended_at: float
    leading_gap: LeadingGap = "none"


class KeyDecoder:
    """Group timed dit/dah elements into Morse symbols."""

    def __init__(
        self,
        *,
        dit_seconds: float,
        character_gap_dits: int = 3,
        character_gap_seconds: float | None = None,
        word_gap_seconds: float | None = None,
    ) -> None:
        if dit_seconds <= 0:
            raise ValueError(f"dit_seconds must be positive, got {dit_seconds}")
        if character_gap_dits <= 0:
            raise ValueError(f"character_gap_dits must be positive, got {character_gap_dits}")
        if character_gap_seconds is not None and character_gap_seconds <= 0:
            raise ValueError(f"character_gap_seconds must be positive, got {character_gap_seconds}")
        if word_gap_seconds is not None and word_gap_seconds <= 0:
            raise ValueError(f"word_gap_seconds must be positive, got {word_gap_seconds}")

        self._dit_seconds = dit_seconds
        self._character_gap_seconds = character_gap_seconds or dit_seconds * character_gap_dits
        self._word_gap_seconds = word_gap_seconds or dit_seconds * 7
        self._marks: list[str] = []
        self._started_at: float | None = None
        self._last_element_end: float | None = None
        self._leading_gap: LeadingGap = "none"

    def push(self, element: KeyElement) -> DecodedSymbol | None:
        """Add an element and return a symbol if this element starts a new one."""
        mark = _ELEMENT_TO_MARK.get(element.kind)
        if mark is None:
            raise ValueError(f"unknown key element kind {element.kind!r}")
        if element.ended_at < element.started_at:
            raise ValueError("key element end timestamp cannot be before its start")

        decoded = None
        if self._last_element_end is not None:
            gap_seconds = element.started_at - self._last_element_end
            if gap_seconds < 0:
                raise ValueError("key element timestamps must be monotonic")
            if self._marks and gap_seconds + _TIMING_EPSILON_SECONDS >= self._character_gap_seconds:
                decoded = self._flush()
                self._leading_gap = "word" if gap_seconds >= self._word_gap_seconds else "character"

        if self._started_at is None:
            self._started_at = element.started_at
        self._marks.append(mark)
        self._last_element_end = element.ended_at
        return decoded

    def tick(self, timestamp: float) -> DecodedSymbol | None:
        """Finalize the current symbol if enough silence has elapsed."""
        if not self._marks or self._last_element_end is None:
            return None
        if timestamp < self._last_element_end:
            raise ValueError("tick timestamp cannot be before the last element ended")
        if (
            timestamp - self._last_element_end + _TIMING_EPSILON_SECONDS
            < self._character_gap_seconds
        ):
            return None
        return self._flush()

    def reset(self) -> None:
        """Clear any partially entered symbol."""
        self._marks = []
        self._started_at = None
        self._last_element_end = None
        self._leading_gap = "none"

    def _flush(self) -> DecodedSymbol:
        pattern = "".join(self._marks)
        assert self._started_at is not None
        assert self._last_element_end is not None
        decoded = DecodedSymbol(
            pattern=pattern,
            symbol=_PATTERN_TO_SYMBOL.get(pattern),
            started_at=self._started_at,
            ended_at=self._last_element_end,
            leading_gap=self._leading_gap,
        )
        self.reset()
        return decoded
