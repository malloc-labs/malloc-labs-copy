"""Short copy exercises drawn from the claimed symbol set.

Display-only first cut: produces ``exercise_count`` sentence-shaped
exercises — each a sequence of short words separated by spaces — built
from the learner's claimed symbols (e.g. with ``{K, M, U}``:
``"K MU KMM U KU"``). Used by the Cadence page's Copy section.

Discipline mirrors :mod:`copy_653.sequence.generator` — see spec §2.8
(per-call ``Random`` instance, recorded seed for replay) and §1.5 (bad
inputs raise; no silent defaults). Pure: no I/O, no clock, no
module-level random state.

Once the claimed set covers enough letters to intersect real words,
the per-word generator will switch to lexicon-backed selection
(``foundation_lexicon.json``); the function signature here is meant to
survive that transition.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from random import Random
from typing import Iterable

from copy_653.audio import patterns

DEFAULT_EXERCISE_COUNT = 5
DEFAULT_MIN_WORDS = 1
DEFAULT_MAX_WORDS = 3
DEFAULT_MIN_WORD_LENGTH = 1
DEFAULT_MAX_WORD_LENGTH = 3


@dataclass(frozen=True, slots=True)
class CopyExercises:
    """A list of short copy exercises with the seed that produced them.

    Attributes
    ----------
    exercises:
        The exercises, in display order. Each entry is a sentence:
        one or more non-empty words of uppercase characters drawn
        from ``claimed_set``, separated by single spaces.
    seed:
        The seed used to instantiate the per-call ``Random``. Always
        concrete — if the caller passed ``None``, this is the seed
        that was generated on their behalf. Replaying with the same
        seed and arguments reproduces ``exercises`` exactly.
    claimed_set:
        The symbol set the exercises were drawn from, in the order
        the caller supplied.
    """

    exercises: tuple[str, ...]
    seed: int
    claimed_set: tuple[str, ...]


def generate_copy_exercises(
    *,
    claimed_set: Iterable[str],
    exercise_count: int = DEFAULT_EXERCISE_COUNT,
    min_words: int = DEFAULT_MIN_WORDS,
    max_words: int = DEFAULT_MAX_WORDS,
    min_word_length: int = DEFAULT_MIN_WORD_LENGTH,
    max_word_length: int = DEFAULT_MAX_WORD_LENGTH,
    seed: int | None = None,
) -> CopyExercises:
    """Generate ``exercise_count`` sentence-shaped exercises.

    For each exercise, a word count is drawn uniformly from
    ``[min_words, max_words]``; for each word a length is drawn
    uniformly from ``[min_word_length, max_word_length]``; each
    character is drawn uniformly with replacement from ``claimed_set``.
    All choices share one per-call ``Random`` so the whole result is
    reproducible from ``seed``.

    Parameters
    ----------
    claimed_set:
        The symbols the learner has claimed competence in. Must be
        non-empty, contain no duplicates, and contain only symbols
        present in :data:`copy_653.audio.patterns.PATTERNS`.
    exercise_count:
        Number of exercises to produce. Must be positive.
    min_words, max_words:
        Inclusive bounds on the words per sentence. Both must be
        ``>= 1`` and ``min_words <= max_words``.
    min_word_length, max_word_length:
        Inclusive bounds on the characters per word. Both must be
        ``>= 1`` and ``min_word_length <= max_word_length``.
    seed:
        Optional explicit seed. If ``None``, a fresh 64-bit seed is
        drawn from :func:`secrets.randbits` and recorded in the
        result.

    Raises
    ------
    ValueError
        If ``claimed_set`` is empty, contains duplicates, or contains
        a symbol with no defined CW pattern; if ``exercise_count`` is
        non-positive; or if the word-count or word-length bounds are
        invalid.
    """
    claimed_tuple = tuple(claimed_set)
    if not claimed_tuple:
        raise ValueError("claimed_set must be non-empty")
    if len(set(claimed_tuple)) != len(claimed_tuple):
        raise ValueError(f"claimed_set contains duplicates: {claimed_tuple!r}")
    for symbol in claimed_tuple:
        try:
            patterns.pattern_for(symbol)
        except KeyError as exc:
            raise ValueError(f"claimed_set contains unknown symbol {exc.args[0]!r}") from exc
    if exercise_count <= 0:
        raise ValueError(f"exercise_count must be positive, got {exercise_count}")
    if min_words < 1:
        raise ValueError(f"min_words must be >= 1, got {min_words}")
    if max_words < min_words:
        raise ValueError(f"max_words must be >= min_words, got min={min_words} max={max_words}")
    if min_word_length < 1:
        raise ValueError(f"min_word_length must be >= 1, got {min_word_length}")
    if max_word_length < min_word_length:
        raise ValueError(
            "max_word_length must be >= min_word_length, "
            f"got min={min_word_length} max={max_word_length}"
        )

    if seed is None:
        seed = secrets.randbits(64)
    rng = Random(seed)

    exercises: list[str] = []
    for _ in range(exercise_count):
        word_count = rng.randint(min_words, max_words)
        words: list[str] = []
        for _ in range(word_count):
            length = rng.randint(min_word_length, max_word_length)
            words.append("".join(rng.choice(claimed_tuple) for _ in range(length)))
        exercises.append(" ".join(words))

    return CopyExercises(
        exercises=tuple(exercises),
        seed=seed,
        claimed_set=claimed_tuple,
    )
