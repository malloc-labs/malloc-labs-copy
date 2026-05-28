"""Lexicon loading and validation (phase 1 of voice input).

A lexicon maps each CW symbol (the keys of
:data:`copy_653.audio.patterns.PATTERNS`) to a list of spoken phrases
that should resolve to it. The on-disk format is one JSON file per
category per language, e.g.::

    src/copy_653/assets/lexicon/
        nato_en.json       # letters
        digits_en.json     # digits
        prosigns_en.json   # punctuation / prosigns
        aliases_en.json    # operator and civilian variants (opt-in)

Each file looks like::

    {
        "name": "NATO phonetic alphabet, English",
        "language": "en",
        "category": "letters",
        "entries": {"A": ["alpha"], "B": ["bravo"], ...}
    }

:func:`load_lexicon` globs every file matching ``*_<language>.json``
in the assets directory, merges the per-symbol phrase lists, and
validates the result. Per the project honesty contract
(``CLAUDE.md`` and spec §1.5), validation failures *raise*; the
function never silently drops data or falls back to a partial
lexicon.

Validation rules:

* Every symbol key must appear in
  :data:`copy_653.audio.patterns.PATTERNS` (no symbol typos).
* Each spoken phrase must be unique across the merged lexicon —
  the same phrase cannot map to two different symbols, and the
  same (symbol, phrase) pair cannot be declared twice.
* Every symbol in :data:`copy_653.audio.patterns.KOCH_ORDER` must
  end up with at least one phrase (no Koch-curriculum gaps).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from copy_653.audio.patterns import KOCH_ORDER, PATTERNS

DEFAULT_LEXICON_DIR: Path = Path(__file__).resolve().parent.parent / "assets" / "lexicon"


class LexiconError(ValueError):
    """Raised when a lexicon file or merge violates the validation contract."""


@dataclass(frozen=True, slots=True)
class Lexicon:
    """A merged, validated symbol → phrases mapping for one language.

    ``entries`` is keyed by canonical symbol (e.g. ``"A"``, ``"5"``,
    ``"?"``) and maps to the tuple of spoken phrases that resolve to
    that symbol. Phrases are lower-case, single- or multi-word
    strings; multi-word phrases use a single space as separator (e.g.
    ``"x ray"``, ``"question mark"``).
    """

    language: str
    entries: Mapping[str, tuple[str, ...]]
    source_files: tuple[Path, ...] = field(default_factory=tuple)

    def phrases(self) -> tuple[str, ...]:
        """Return every spoken phrase, sorted, with no duplicates."""
        seen: set[str] = set()
        for phrase_list in self.entries.values():
            seen.update(phrase_list)
        return tuple(sorted(seen))

    def symbol_for(self, phrase: str) -> str | None:
        """Return the symbol a spoken phrase resolves to, or ``None``."""
        for symbol, phrase_list in self.entries.items():
            if phrase in phrase_list:
                return symbol
        return None


def load_lexicon(
    language: str = "en",
    *,
    lexicon_dir: Path | None = None,
) -> Lexicon:
    """Load and merge every ``*_<language>.json`` file under ``lexicon_dir``.

    Raises :class:`LexiconError` on:

    * unknown symbol (not in :data:`PATTERNS`)
    * duplicate phrase (same phrase declared twice, or mapping to two
      different symbols)
    * a :data:`KOCH_ORDER` symbol with no phrases after merge
    """
    directory = lexicon_dir if lexicon_dir is not None else DEFAULT_LEXICON_DIR
    if not directory.is_dir():
        raise LexiconError(f"lexicon directory not found: {directory}")

    files = sorted(directory.glob(f"*_{language}.json"))
    if not files:
        raise LexiconError(f"no lexicon files found for language {language!r} in {directory}")

    merged: dict[str, list[str]] = {}
    phrase_origin: dict[str, tuple[str, Path]] = {}

    for path in files:
        per_file = _load_file(path, language=language)
        for symbol, phrases in per_file.items():
            if symbol not in PATTERNS:
                raise LexiconError(f"{path.name}: symbol {symbol!r} is not a known CW pattern")
            for phrase in phrases:
                prior = phrase_origin.get(phrase)
                if prior is not None:
                    prior_symbol, prior_path = prior
                    raise LexiconError(
                        f"duplicate phrase {phrase!r}: "
                        f"already mapped to {prior_symbol!r} in {prior_path.name}, "
                        f"redeclared for {symbol!r} in {path.name}"
                    )
                phrase_origin[phrase] = (symbol, path)
                merged.setdefault(symbol, []).append(phrase)

    _assert_koch_coverage(merged)

    frozen = MappingProxyType(
        {symbol: tuple(phrases) for symbol, phrases in sorted(merged.items())}
    )
    return Lexicon(language=language, entries=frozen, source_files=tuple(files))


def _load_file(path: Path, *, language: str) -> dict[str, list[str]]:
    """Read one lexicon file and shape-check it. Does not merge."""
    try:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except json.JSONDecodeError as err:
        raise LexiconError(f"{path.name}: invalid JSON: {err}") from err

    if not isinstance(payload, dict):
        raise LexiconError(f"{path.name}: top-level must be a JSON object")

    declared = payload.get("language")
    if declared != language:
        raise LexiconError(f"{path.name}: language field is {declared!r}, expected {language!r}")

    entries = payload.get("entries")
    if not isinstance(entries, dict):
        raise LexiconError(f"{path.name}: 'entries' must be a JSON object")

    cleaned: dict[str, list[str]] = {}
    seen_in_file: dict[str, str] = {}
    for symbol, phrase_list in entries.items():
        if not isinstance(symbol, str) or not symbol:
            raise LexiconError(f"{path.name}: symbol keys must be non-empty strings")
        if not isinstance(phrase_list, list) or not phrase_list:
            raise LexiconError(
                f"{path.name}: entry for {symbol!r} must be a non-empty list of strings"
            )
        cleaned_phrases: list[str] = []
        for phrase in phrase_list:
            if not isinstance(phrase, str) or not phrase.strip():
                raise LexiconError(
                    f"{path.name}: entry {symbol!r} has a non-string or empty phrase"
                )
            normalised = phrase.strip().lower()
            if normalised != phrase:
                raise LexiconError(f"{path.name}: phrase {phrase!r} must be lower-case and trimmed")
            if normalised in seen_in_file:
                raise LexiconError(
                    f"{path.name}: phrase {normalised!r} appears twice "
                    f"(under {seen_in_file[normalised]!r} and {symbol!r})"
                )
            seen_in_file[normalised] = symbol
            cleaned_phrases.append(normalised)
        cleaned[symbol] = cleaned_phrases
    return cleaned


def _assert_koch_coverage(merged: Mapping[str, Iterable[str]]) -> None:
    """Raise if any :data:`KOCH_ORDER` symbol has no phrases."""
    missing = [s for s in KOCH_ORDER if not merged.get(s)]
    if missing:
        raise LexiconError("Koch curriculum symbols have no spoken phrases: " + ", ".join(missing))
