"""Copy → Key exercise generation.

Produces ``exercise_count`` short exercises for the Copy Key mode:
the learner hears each exercise played as audio, head-copies it, and
keys it back. Exercises are single words of 1-3 symbols at the lower
end of the range, scaling to a maximum of 2 words / 5 total symbols
at the top.

The generator reuses the two-layer pool-and-band approach from
:mod:`copy_653.sequence.copy_exercises` — a candidate pool is drawn,
scored, sorted, and one pick is taken per burden band — but with
constraints and scoring tuned for head-copy difficulty rather than
read-and-send difficulty.

Key differences from Cadence exercise generation:

* **Tighter size ceiling.** Max 2 words, max 4 symbols per word, max
  5 total symbols. Gear 0 is tighter still: the top two bands cap
  at 4 total symbols, lower bands at 3. The floor is a single symbol.
* **Simpler scoring.** Total symbol count dominates; word gaps carry
  significant weight because hearing a space and holding two groups
  is a qualitative jump in cognitive load. Symbol diversity and
  switches are secondary.
* **No RST sub-axis.** Copy Key does not modulate the receiver bed
  per-exercise — the audio difficulty is the head-copy task itself.

Pure: no I/O, no clock, no module-level random state.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from random import Random
from typing import Iterable

from copy_653.audio import patterns

MAX_GEAR = 3
MAX_CONTENT_GEAR = 2

DEFAULT_EXERCISE_COUNT = 5
DEFAULT_MAX_WORDS = 2
DEFAULT_MAX_WORD_LENGTH = 4
DEFAULT_MAX_TOTAL_SYMBOLS = 5
DEFAULT_MAX_IDENTICAL_RUN = 2
DEFAULT_CANDIDATE_MULTIPLIER = 4
GEAR_ZERO_UPPER_MAX_SYMBOLS = 4
GEAR_ZERO_LOWER_MAX_SYMBOLS = 3


@dataclass(frozen=True, slots=True)
class CopyKeyExercises:
    """Generated Copy Key exercises with provenance.

    Attributes
    ----------
    exercises:
        Selected exercises in non-decreasing score order. Each is a
        space-separated string of words drawn from ``claimed_set``.
    seed:
        The seed used (or generated) for this call.
    claimed_set:
        The symbol set used, in caller-supplied order.
    scores:
        Abstract-burden scores parallel to ``exercises``.
    candidate_count:
        Size of the underlying candidate pool.
    """

    exercises: tuple[str, ...]
    seed: int
    claimed_set: tuple[str, ...]
    scores: tuple[int, ...] = ()
    candidate_count: int = 0


def _score_copy_key_exercise(exercise: str) -> int:
    """Abstract-burden score tuned for head-copy difficulty.

    Total symbol count is the primary driver — each extra symbol held
    in memory adds load. Word gaps carry heavy weight because holding
    two groups requires chunking. Symbol diversity and switches are
    secondary since even identical symbols must be counted and held.
    """
    words = exercise.split(" ")
    symbols = [ch for word in words for ch in word]

    total_symbols = len(symbols)
    word_count = len(words)
    unique_symbols = len(set(symbols))
    symbol_switches = sum(1 for a, b in zip(symbols, symbols[1:]) if a != b)
    word_gaps = max(0, word_count - 1)

    return total_symbols * 12 + word_gaps * 14 + unique_symbols * 3 + symbol_switches * 2


def _has_identical_run(exercise: str, *, max_run: int) -> bool:
    compact = exercise.replace(" ", "")
    current = 0
    previous = ""
    for symbol in compact:
        if symbol == previous:
            current += 1
        else:
            previous = symbol
            current = 1
        if current > max_run:
            return True
    return False


def _slot_range(
    band_index: int,
    exercise_count: int,
    candidate_count: int,
    gear: int,
) -> tuple[int, int]:
    """Return the ``(lo, hi)`` slice for this band at the given gear.

    Same escalation semantics as the Cadence version: gear 0 draws
    from the band's own range, gear 1 from the upper half, gear 2+
    from the next band up (or upper-half at the top slot). Gear 3 is
    content-equivalent to gear 2.
    """
    content_gear = min(gear, MAX_CONTENT_GEAR)
    if content_gear == 2 and band_index < exercise_count - 1:
        source_band = band_index + 1
        lo = source_band * candidate_count // exercise_count
        hi = (source_band + 1) * candidate_count // exercise_count
    else:
        lo = band_index * candidate_count // exercise_count
        hi = (band_index + 1) * candidate_count // exercise_count
        if content_gear >= 1 and hi - lo > 1:
            lo = (lo + hi) // 2

    if lo == hi:
        lo = min(band_index, candidate_count - 1)
        hi = lo + 1
    return lo, hi


def generate_copy_key_exercises(
    *,
    claimed_set: Iterable[str],
    exercise_count: int = DEFAULT_EXERCISE_COUNT,
    candidate_count: int | None = None,
    seed: int | None = None,
    gears: list[int] | None = None,
    max_identical_run: int | None = DEFAULT_MAX_IDENTICAL_RUN,
    max_words: int = DEFAULT_MAX_WORDS,
    max_word_length: int = DEFAULT_MAX_WORD_LENGTH,
    max_total_symbols: int = DEFAULT_MAX_TOTAL_SYMBOLS,
) -> CopyKeyExercises:
    """Generate ``exercise_count`` head-copy exercises.

    Each candidate is a 1-2 word phrase where each word is 1-4
    symbols and the total symbol count is at most 5. Gear 0 filters
    further: top two bands allow up to 4 symbols, lower bands cap
    at 3. The candidate pool is scored, banded, and one pick is
    taken per band — same mechanics as Cadence, different constraints.

    Parameters
    ----------
    claimed_set:
        Non-empty set of symbols the learner has claimed.
    exercise_count:
        Number of exercises to produce.
    candidate_count:
        Pool size. Defaults to ``4 * exercise_count``.
    seed:
        Optional explicit seed for reproducibility.
    gears:
        Optional per-slot gear list (same semantics as Cadence).
    max_identical_run:
        Reject candidates with longer runs of the same symbol.
    max_words:
        Maximum number of words per exercise (default 2).
    max_word_length:
        Maximum symbols per word (default 4).
    max_total_symbols:
        Maximum total symbols across all words (default 5).
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
    if max_words < 1:
        raise ValueError(f"max_words must be >= 1, got {max_words}")
    if max_word_length < 1:
        raise ValueError(f"max_word_length must be >= 1, got {max_word_length}")
    if max_total_symbols < 1:
        raise ValueError(f"max_total_symbols must be >= 1, got {max_total_symbols}")
    if max_identical_run is not None and max_identical_run < 1:
        raise ValueError(f"max_identical_run must be >= 1, got {max_identical_run}")

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
    attempts_remaining = max(candidate_count * 100, 1000)
    while len(candidates) < candidate_count and attempts_remaining > 0:
        attempts_remaining -= 1
        word_count = rng.randint(1, max_words)
        words: list[str] = []
        total = 0
        for _ in range(word_count):
            remaining = max_total_symbols - total
            if remaining <= 0:
                break
            length = rng.randint(1, min(max_word_length, remaining))
            words.append("".join(rng.choice(claimed_tuple) for _ in range(length)))
            total += length
        candidate = " ".join(words)
        if max_identical_run is not None and _has_identical_run(
            candidate, max_run=max_identical_run
        ):
            continue
        candidates.append(candidate)
    if len(candidates) < candidate_count:
        raise ValueError(
            "constraints prevent drawing enough copy-key candidates, "
            f"got {len(candidates)} of {candidate_count}"
        )

    scored = sorted(
        ((_score_copy_key_exercise(ex), idx, ex) for idx, ex in enumerate(candidates)),
        key=lambda triple: (triple[0], triple[1]),
    )

    picks: list[tuple[int, str]] = []
    for band_index in range(exercise_count):
        gear = 0
        if gears is not None and band_index < len(gears):
            raw_gear = gears[band_index]
            if isinstance(raw_gear, int) and not isinstance(raw_gear, bool):
                gear = max(0, min(MAX_GEAR, raw_gear))
        lo, hi = _slot_range(band_index, exercise_count, candidate_count, gear)
        if gear == 0:
            cap = (
                GEAR_ZERO_UPPER_MAX_SYMBOLS
                if band_index >= exercise_count - 2
                else GEAR_ZERO_LOWER_MAX_SYMBOLS
            )
            capped = [t for t in scored if len(t[2].replace(" ", "")) <= cap]
            if capped:
                c_lo = band_index * len(capped) // exercise_count
                c_hi = (band_index + 1) * len(capped) // exercise_count
                if c_lo == c_hi:
                    c_lo = min(band_index, len(capped) - 1)
                    c_hi = c_lo + 1
                band_slice = capped[c_lo:c_hi]
            else:
                band_slice = scored[lo:hi]
        else:
            band_slice = scored[lo:hi]
        score, _idx, exercise = rng.choice(band_slice)
        picks.append((score, exercise))

    picks.sort(key=lambda pair: pair[0])

    return CopyKeyExercises(
        exercises=tuple(ex for _, ex in picks),
        seed=seed,
        claimed_set=claimed_tuple,
        scores=tuple(score for score, _ in picks),
        candidate_count=candidate_count,
    )
