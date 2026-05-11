"""Word-detection stream generation from the foundation lexicon.

Word Detection is intentionally different from the traditional Koch symbol
stream. The learner's claimed symbols are focus targets, not a restrictive
alphabet. Selected words may contain unknown symbols; the exercise is to hear
claimed symbols inside word-shaped Morse rhythm.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Iterable, Mapping, Sequence

from copy_653.audio import patterns, synth, timing
from copy_653.audio.parameters import AudioParameters

FOUNDATION_LEXICON_SCHEMA_VERSION = 2
FOUNDATION_LEXICON_RELATIVE_PATH = Path("assets") / "lexicon" / "foundation_lexicon.json"


@dataclass(frozen=True, slots=True)
class LexiconEntry:
    """A single foundation lexicon word with Morse rhythm metadata."""

    word: str
    letters: tuple[str, ...]
    morse: str
    length: int
    frequency: int
    frequency_rank: int | None
    commonness: str
    rhythm_signature: str
    rhythm_diversity: float
    transitions: int
    repeat_pressure: str
    dit_count: int
    dah_count: int


@dataclass(frozen=True, slots=True)
class WordSymbol:
    """A symbol emitted as part of a selected word."""

    symbol: str
    word_index: int
    word: str


@dataclass(frozen=True, slots=True)
class GeneratedWordDetection:
    """A rendered word-detection stream and the seed that produced it."""

    words: tuple[LexiconEntry, ...]
    symbols: tuple[WordSymbol, ...]
    seed: int
    focus_set: tuple[str, ...]
    lexicon_schema_version: int
    ranking: str


def find_foundation_lexicon() -> Path:
    """Locate the bundled foundation lexicon in the editable repository layout."""

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / FOUNDATION_LEXICON_RELATIVE_PATH
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Could not locate {FOUNDATION_LEXICON_RELATIVE_PATH} relative to {here}. "
        "Word Detection requires the bundled foundation lexicon asset."
    )


def load_foundation_lexicon(path: Path | None = None) -> tuple[int, tuple[LexiconEntry, ...]]:
    """Load and validate the schema-2 foundation lexicon asset."""

    lexicon_path = path if path is not None else find_foundation_lexicon()
    data = json.loads(lexicon_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("foundation lexicon must be a JSON object")

    schema_version = data.get("schema_version")
    if schema_version != FOUNDATION_LEXICON_SCHEMA_VERSION:
        raise ValueError(
            "foundation lexicon schema_version must be "
            f"{FOUNDATION_LEXICON_SCHEMA_VERSION}, got {schema_version!r}"
        )

    raw_words = data.get("words")
    if not isinstance(raw_words, list):
        raise ValueError("foundation lexicon must contain a words list")

    entries = tuple(_entry_from_json(item) for item in raw_words)
    if not entries:
        raise ValueError("foundation lexicon contains no words")
    return schema_version, entries


def generate_word_detection(
    *,
    focus_set: Iterable[str],
    duration_seconds: float,
    params: AudioParameters,
    lexicon: Sequence[LexiconEntry] | None = None,
    lexicon_schema_version: int = FOUNDATION_LEXICON_SCHEMA_VERSION,
    seed: int | None = None,
) -> GeneratedWordDetection:
    """Generate a duration-bounded focus-letter word-detection stream.

    ``focus_set`` is the current claimed Koch character set. A word is eligible
    when it contains one or more focus characters, even if it also contains
    unknown characters. Candidates are ordered by the same rhythmically diverse
    ranking used by the lexicon CLI, then a seeded rotation chooses a replayable
    starting point so repeated sessions do not always begin with the same words.
    """

    focus_tuple = _validate_focus_set(focus_set)
    if duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be positive, got {duration_seconds}")

    if lexicon is None:
        lexicon_schema_version, loaded = load_foundation_lexicon()
        lexicon = loaded

    candidates = [
        entry for entry in lexicon if set(entry.letters) & {s.lower() for s in focus_tuple}
    ]
    if not candidates:
        raise ValueError(f"no foundation lexicon words contain focus symbols {focus_tuple!r}")

    ranked = _rank_rhythmically_diverse(candidates)
    if seed is None:
        seed = secrets.randbits(64)
    rng = Random(seed)
    start = rng.randrange(len(ranked))
    ordered = ranked[start:] + ranked[:start]

    words: list[LexiconEntry] = []
    cumulative = 0.0
    for entry in ordered:
        increment = _word_increment_seconds(entry.word, params, has_previous=bool(words))
        if cumulative + increment > duration_seconds:
            continue
        words.append(entry)
        cumulative += increment

    if not words:
        return GeneratedWordDetection(
            words=(),
            symbols=(),
            seed=seed,
            focus_set=focus_tuple,
            lexicon_schema_version=lexicon_schema_version,
            ranking="rhythmic-diverse",
        )

    symbols = tuple(
        WordSymbol(symbol=letter.upper(), word_index=index, word=entry.word)
        for index, entry in enumerate(words, start=1)
        for letter in entry.word
    )
    return GeneratedWordDetection(
        words=tuple(words),
        symbols=symbols,
        seed=seed,
        focus_set=focus_tuple,
        lexicon_schema_version=lexicon_schema_version,
        ranking="rhythmic-diverse",
    )


def _entry_from_json(item: object) -> LexiconEntry:
    if not isinstance(item, Mapping):
        raise ValueError("foundation lexicon words must be JSON objects")

    word = _required_str(item, "word").lower()
    letters_raw = item.get("letters")
    if not isinstance(letters_raw, list) or not all(
        isinstance(letter, str) for letter in letters_raw
    ):
        raise ValueError(f"lexicon entry {word!r} has invalid letters")

    return LexiconEntry(
        word=word,
        letters=tuple(letter.lower() for letter in letters_raw),
        morse=_required_str(item, "morse"),
        length=_required_int(item, "length"),
        frequency=_required_int(item, "frequency"),
        frequency_rank=(
            item.get("frequency_rank") if isinstance(item.get("frequency_rank"), int) else None
        ),
        commonness=_required_str(item, "commonness"),
        rhythm_signature=_required_str(item, "rhythm_signature"),
        rhythm_diversity=_required_float(item, "rhythm_diversity"),
        transitions=_required_int(item, "transitions"),
        repeat_pressure=_required_str(item, "repeat_pressure"),
        dit_count=_required_int(item, "dit_count"),
        dah_count=_required_int(item, "dah_count"),
    )


def _validate_focus_set(focus_set: Iterable[str]) -> tuple[str, ...]:
    focus_tuple = tuple(symbol.upper() for symbol in focus_set)
    if not focus_tuple:
        raise ValueError("focus_set must be non-empty")
    if len(set(focus_tuple)) != len(focus_tuple):
        raise ValueError(f"focus_set contains duplicates: {focus_tuple!r}")
    for symbol in focus_tuple:
        try:
            patterns.pattern_for(symbol)
        except KeyError as exc:
            raise ValueError(f"focus_set contains unknown symbol {exc.args[0]!r}") from exc
    return focus_tuple


def _rank_rhythmically_diverse(entries: Sequence[LexiconEntry]) -> list[LexiconEntry]:
    return sorted(
        entries,
        key=lambda entry: (
            -entry.rhythm_diversity,
            -entry.transitions,
            -(entry.dit_count + entry.dah_count),
            entry.word,
        ),
    )


def _word_increment_seconds(word: str, params: AudioParameters, *, has_previous: bool) -> float:
    total = timing.inter_word_seconds(params) if has_previous else 0.0
    for index, symbol in enumerate(word.upper()):
        if index > 0:
            total += timing.inter_character_seconds(params)
        total += synth.symbol_duration_seconds(symbol, params)
    return total


def _required_str(item: Mapping[str, object], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"lexicon entry missing string field {key!r}")
    return value


def _required_int(item: Mapping[str, object], key: str) -> int:
    value = item.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"lexicon entry missing integer field {key!r}")
    return value


def _required_float(item: Mapping[str, object], key: str) -> float:
    value = item.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"lexicon entry missing numeric field {key!r}")
    return float(value)
