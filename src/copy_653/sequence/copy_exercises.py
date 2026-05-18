"""Short copy exercises drawn from the claimed symbol set.

Display-only first cut: produces ``exercise_count`` sentence-shaped
exercises — each a sequence of short words separated by spaces — built
from the learner's claimed symbols (e.g. with ``{K, M, U}``:
``"K MU KMM U KU"``). Used by the Cadence page's Copy section.

Two-layer generator (see ``docs/notes/cadence-difficulty.md``). A pool
of ``candidate_count`` exercises is drawn uniformly, each is scored by
abstract-burden cost (length, word gaps, symbol switches, …), and one
candidate is chosen at random from each of ``exercise_count``
equal-width quantile bands of that ranking. The returned exercises are
displayed in non-decreasing score order so the first item is the
least-burdensome and the last the most. This is *invisible pedagogy*:
no scores are surfaced to the learner, only to the session record for
later analysis.

Discipline mirrors :mod:`copy_653.sequence.generator` — see spec §2.8
(per-call ``Random`` instance, recorded seed for replay) and §1.5 (bad
inputs raise; no silent defaults). Pure: no I/O, no clock, no
module-level random state.

Once the claimed set covers enough letters to intersect real words,
the per-word generator will switch to lexicon-backed selection
(``foundation_lexicon.json``) and the scorer will gain a chunkability
credit; the function signature here is meant to survive that
transition.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from random import Random
from typing import Iterable

from copy_653.audio import patterns

DEFAULT_EXERCISE_COUNT = 5
DEFAULT_MIN_WORDS = 1
# Cap the default sentence at two groups. Three-group exercises like
# ``KKM UU UKM`` overload the early K/M/U stage even at the hardest
# end of the ramp — see ``docs/notes/cadence-difficulty.md`` §1.
DEFAULT_MAX_WORDS = 2
DEFAULT_MIN_WORD_LENGTH = 1
DEFAULT_MAX_WORD_LENGTH = 3
# Default candidate pool is 4× the displayed count. With the default
# ``exercise_count=5`` this gives a pool of 20, matching the size the
# notes argue gives bands wide enough to feel random within each band.
DEFAULT_CANDIDATE_MULTIPLIER = 4


@dataclass(frozen=True, slots=True)
class CopyExercises:
    """A list of short copy exercises with the seed that produced them.

    Attributes
    ----------
    exercises:
        The selected exercises, in non-decreasing score order. Each
        entry is a sentence: one or more non-empty words of uppercase
        characters drawn from ``claimed_set``, separated by single
        spaces.
    seed:
        The seed used to instantiate the per-call ``Random``. Always
        concrete — if the caller passed ``None``, this is the seed
        that was generated on their behalf. Replaying with the same
        seed and arguments reproduces ``exercises`` exactly.
    claimed_set:
        The symbol set the exercises were drawn from, in the order
        the caller supplied.
    scores:
        Abstract-burden scores parallel to ``exercises`` (same index,
        same length). Non-decreasing. Captured for session records
        and analysis only; not surfaced to the learner.
    candidate_count:
        Size of the underlying random pool the selected exercises
        were drawn from.
    """

    exercises: tuple[str, ...]
    seed: int
    claimed_set: tuple[str, ...]
    scores: tuple[int, ...] = ()
    candidate_count: int = 0


def _slot_range(
    band_index: int,
    exercise_count: int,
    candidate_count: int,
    gear: int,
) -> tuple[int, int]:
    """Return the ``(lo, hi)`` slice into the sorted candidate pool
    that slot ``band_index`` should draw from at this gear.

    The slot's own band is at ``band_index``. Gear 2 redirects the
    draw to ``band_index + 1`` — except at the top slot, where there
    is nowhere to escalate and gear 2 quietly falls back to gear 1
    (upper half of the slot's own band). Gear 1 always halves whatever
    band has been resolved.
    """
    if gear == 2 and band_index < exercise_count - 1:
        source_band = band_index + 1
        lo = source_band * candidate_count // exercise_count
        hi = (source_band + 1) * candidate_count // exercise_count
    else:
        lo = band_index * candidate_count // exercise_count
        hi = (band_index + 1) * candidate_count // exercise_count
        if gear >= 1 and hi - lo > 1:
            # Gear 1, or gear 2 capped at the top band: upper half.
            lo = (lo + hi) // 2

    # ``lo == hi`` cannot happen given the candidate_count >=
    # exercise_count check upstream, but be defensive so we never
    # hand an empty slice to rng.choice.
    if lo == hi:
        lo = min(band_index, candidate_count - 1)
        hi = lo + 1
    return lo, hi


def _score_copy_exercise(exercise: str) -> int:
    """Abstract-burden score: higher means heavier off-screen copy load.

    The weights below are deliberately human-readable; tune by
    incrementing the term whose contribution feels too small in
    practice. See ``docs/notes/cadence-difficulty.md`` §4.
    """
    words = exercise.split(" ")
    symbols = [ch for word in words for ch in word]

    total_symbols = len(symbols)
    word_count = len(words)
    longest_word = max((len(word) for word in words), default=0)
    unique_symbols = len(set(symbols))
    symbol_switches = sum(1 for a, b in zip(symbols, symbols[1:]) if a != b)
    word_gaps = max(0, word_count - 1)

    return (
        total_symbols * 10
        + word_count * 6
        + longest_word * 4
        + unique_symbols * 3
        + symbol_switches * 2
        + word_gaps * 8
    )


def generate_copy_exercises(
    *,
    claimed_set: Iterable[str],
    exercise_count: int = DEFAULT_EXERCISE_COUNT,
    min_words: int = DEFAULT_MIN_WORDS,
    max_words: int = DEFAULT_MAX_WORDS,
    min_word_length: int = DEFAULT_MIN_WORD_LENGTH,
    max_word_length: int = DEFAULT_MAX_WORD_LENGTH,
    candidate_count: int | None = None,
    seed: int | None = None,
    gears: list[int] | None = None,
) -> CopyExercises:
    """Generate ``exercise_count`` sentence-shaped exercises.

    A pool of ``candidate_count`` candidates is drawn uniformly — for
    each candidate, a word count is sampled from
    ``[min_words, max_words]``, then per word a length from
    ``[min_word_length, max_word_length]``, then per character a symbol
    uniformly from ``claimed_set``. Candidates are scored by
    :func:`_score_copy_exercise`, sorted ascending, and split into
    ``exercise_count`` contiguous equal-width bands; one candidate is
    chosen from each band with the same per-call ``Random``. The
    returned exercises are then ordered by score so the first item is
    the easiest and the last is the hardest.

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
    candidate_count:
        Size of the candidate pool. Defaults to
        ``DEFAULT_CANDIDATE_MULTIPLIER * exercise_count`` (20 for the
        default ``exercise_count=5``). Must be ``>= exercise_count``
        so every band can yield at least one pick.
    seed:
        Optional explicit seed. If ``None``, a fresh 64-bit seed is
        drawn from :func:`secrets.randbits` and recorded in the
        result.
    gears:
        Optional per-slot gear shift, parallel to ``exercise_count``.
        Entry ``i`` controls how slot ``i`` selects from the sorted
        candidate pool:

        * ``0`` (default) — pick from slot ``i``'s own quantile band.
        * ``1`` — pick from the upper half of slot ``i``'s band.
        * ``2`` — pick from the next-higher band's full range. At the
          top slot, gear 2 falls back to gear 1 behaviour because
          there is nowhere to escalate to.

        Higher gears are clamped to 2 — values 3+ are reserved for
        generator-parameter changes that are not yet implemented.

    Raises
    ------
    ValueError
        If ``claimed_set`` is empty, contains duplicates, or contains
        a symbol with no defined CW pattern; if ``exercise_count`` is
        non-positive; if the word-count or word-length bounds are
        invalid; or if ``candidate_count`` is less than
        ``exercise_count``.
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

    if candidate_count is None:
        candidate_count = DEFAULT_CANDIDATE_MULTIPLIER * exercise_count
    if candidate_count < exercise_count:
        raise ValueError(
            "candidate_count must be >= exercise_count, "
            f"got candidate_count={candidate_count} exercise_count={exercise_count}"
        )

    if seed is None:
        seed = secrets.randbits(64)
    rng = Random(seed)

    candidates: list[str] = []
    for _ in range(candidate_count):
        word_count = rng.randint(min_words, max_words)
        words: list[str] = []
        for _ in range(word_count):
            length = rng.randint(min_word_length, max_word_length)
            words.append("".join(rng.choice(claimed_tuple) for _ in range(length)))
        candidates.append(" ".join(words))

    scored = sorted(
        ((_score_copy_exercise(ex), idx, ex) for idx, ex in enumerate(candidates)),
        key=lambda triple: (triple[0], triple[1]),
    )

    # Contiguous equal-width bands over the sorted index range. Each
    # band has either ``candidate_count // exercise_count`` or one
    # more entries; with the default 20/5 every band has exactly 4.
    picks: list[tuple[int, str]] = []
    for band_index in range(exercise_count):
        gear = 0
        if gears is not None and band_index < len(gears):
            raw_gear = gears[band_index]
            if isinstance(raw_gear, int) and not isinstance(raw_gear, bool):
                gear = max(0, min(2, raw_gear))
        lo, hi = _slot_range(band_index, exercise_count, candidate_count, gear)
        score, _idx, exercise = rng.choice(scored[lo:hi])
        picks.append((score, exercise))

    # ``picks`` already comes out in band order; sort by score to
    # normalise display order across the band-boundary tie case.
    picks.sort(key=lambda pair: pair[0])

    return CopyExercises(
        exercises=tuple(ex for _, ex in picks),
        seed=seed,
        claimed_set=claimed_tuple,
        scores=tuple(score for score, _ in picks),
        candidate_count=candidate_count,
    )
