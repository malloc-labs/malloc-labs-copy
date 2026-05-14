"""Short copy exercises drawn from the claimed symbol set.

Display-only first cut: produces ``exercise_count`` short groupings of
the learner's claimed symbols (e.g. with ``{K, M, U}``: ``K``, ``MK``,
``KMU``, ``MUM``, ...). Used by the Cadence page's Copy section.

Discipline mirrors :mod:`copy_653.sequence.generator` — see spec §2.8
(per-call ``Random`` instance, recorded seed for replay) and §1.5 (bad
inputs raise; no silent defaults). Pure: no I/O, no clock, no
module-level random state.

Once the claimed set covers enough letters to intersect real words,
the generator will switch from random groupings to lexicon-backed
selection (``foundation_lexicon.json``); the function signature here
is meant to survive that transition.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from random import Random
from typing import Iterable

from copy_653.audio import patterns


DEFAULT_EXERCISE_COUNT = 10
DEFAULT_MIN_LENGTH = 1
DEFAULT_MAX_LENGTH = 5


@dataclass(frozen=True, slots=True)
class CopyExercises:
    """A list of short copy exercises with the seed that produced them.

    Attributes
    ----------
    exercises:
        The exercises, in display order. Each entry is a non-empty
        string of uppercase characters drawn from ``claimed_set``.
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
    min_length: int = DEFAULT_MIN_LENGTH,
    max_length: int = DEFAULT_MAX_LENGTH,
    seed: int | None = None,
) -> CopyExercises:
    """Generate ``exercise_count`` short groupings from ``claimed_set``.

    Each exercise's length is drawn uniformly from
    ``[min_length, max_length]``; each character is drawn uniformly
    with replacement from ``claimed_set``. Both choices use the same
    per-call ``Random`` so the whole result is reproducible from
    ``seed``.

    Parameters
    ----------
    claimed_set:
        The symbols the learner has claimed competence in. Must be
        non-empty, contain no duplicates, and contain only symbols
        present in :data:`copy_653.audio.patterns.PATTERNS`.
    exercise_count:
        Number of exercises to produce. Must be positive.
    min_length, max_length:
        Inclusive bounds on the per-exercise character count. Both
        must be ``>= 1`` and ``min_length <= max_length``.
    seed:
        Optional explicit seed. If ``None``, a fresh 64-bit seed is
        drawn from :func:`secrets.randbits` and recorded in the
        result.

    Raises
    ------
    ValueError
        If ``claimed_set`` is empty, contains duplicates, or contains
        a symbol with no defined CW pattern; if ``exercise_count`` is
        non-positive; or if the length bounds are invalid.
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
    if min_length < 1:
        raise ValueError(f"min_length must be >= 1, got {min_length}")
    if max_length < min_length:
        raise ValueError(
            f"max_length must be >= min_length, got min={min_length} max={max_length}"
        )

    if seed is None:
        seed = secrets.randbits(64)
    rng = Random(seed)

    exercises: list[str] = []
    for _ in range(exercise_count):
        length = rng.randint(min_length, max_length)
        chars = [rng.choice(claimed_tuple) for _ in range(length)]
        exercises.append("".join(chars))

    return CopyExercises(
        exercises=tuple(exercises),
        seed=seed,
        claimed_set=claimed_tuple,
    )
