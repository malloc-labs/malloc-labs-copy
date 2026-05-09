"""Per-session symbol stream generation.

See spec §2.5 (symbol-set gating: only claimed symbols enter the
stream), §2.8 (per-session ``Random`` instance, seed recording for
replay, uniform sampling, no forced balance, no run-length cap), and
§1.5 (failures surface plainly: bad inputs raise at session start,
not mid-stream).

The function in this module is pure with respect to the host: it does
not touch the module-level :mod:`random` state, does not perform I/O,
and does not consult a clock. It is the source of truth that the
session record (`session/`, future) replays from.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from random import Random
from typing import Iterable

from copy_653.audio import patterns, synth, timing
from copy_653.audio.parameters import AudioParameters


@dataclass(frozen=True, slots=True)
class GeneratedSequence:
    """A rendered symbol stream with the seed that produced it.

    Attributes
    ----------
    symbols:
        The sequence of symbols, in playback order. Each symbol is a
        single uppercase character drawn from ``claimed_set``.
    seed:
        The seed used to instantiate the per-session ``Random``.
        Always concrete — if the caller passed ``None`` to
        :func:`generate`, this field holds the seed that was generated
        on their behalf. Replaying ``generate`` with the same seed,
        ``claimed_set``, ``duration_seconds`` and audio parameters
        reproduces ``symbols`` exactly.
    claimed_set:
        The symbol set the stream was drawn from, in the order the
        caller supplied. Recorded so a session record carries the
        gating context that produced it.
    """

    symbols: tuple[str, ...]
    seed: int
    claimed_set: tuple[str, ...]


def generate(
    *,
    claimed_set: Iterable[str],
    duration_seconds: float,
    params: AudioParameters,
    seed: int | None = None,
) -> GeneratedSequence:
    """Generate a uniform-random stream from ``claimed_set``.

    The stream's total audio length (sum of symbol durations plus
    inter-character spacing per :mod:`copy_653.audio.timing`) does not
    exceed ``duration_seconds``. The last symbol that would push the
    cumulative length past the target is *not* added — strict uniform
    sampling, no draw-and-retry. Replaying with the same seed produces
    the same stopping point.

    Parameters
    ----------
    claimed_set:
        The symbols the learner has claimed competence in. Must be
        non-empty, contain no duplicates, and contain only symbols
        present in :data:`copy_653.audio.patterns.PATTERNS`.
    duration_seconds:
        Upper bound on the audio duration of the resulting stream.
        Must be positive.
    params:
        Audio parameters; symbol durations and inter-character gaps
        are computed from these.
    seed:
        Optional explicit seed. If ``None``, a fresh 64-bit seed is
        drawn from :func:`secrets.randbits` and recorded in the
        result.

    Raises
    ------
    ValueError
        If ``claimed_set`` is empty, contains duplicates, or contains
        a symbol with no defined CW pattern; or if
        ``duration_seconds`` is non-positive.
    """
    claimed_tuple = tuple(claimed_set)
    if not claimed_tuple:
        raise ValueError("claimed_set must be non-empty")
    if len(set(claimed_tuple)) != len(claimed_tuple):
        raise ValueError(f"claimed_set contains duplicates: {claimed_tuple!r}")
    if duration_seconds <= 0:
        raise ValueError(f"duration_seconds must be positive, got {duration_seconds}")
    for symbol in claimed_tuple:
        try:
            patterns.pattern_for(symbol)
        except KeyError as exc:
            raise ValueError(f"claimed_set contains unknown symbol {exc.args[0]!r}") from exc

    if seed is None:
        seed = secrets.randbits(64)
    rng = Random(seed)

    inter_char = timing.inter_character_seconds(params)
    chosen: list[str] = []
    cumulative = 0.0
    while True:
        next_symbol = rng.choice(claimed_tuple)
        symbol_duration = synth.symbol_duration_seconds(next_symbol, params)
        # First symbol carries no leading inter-character gap; every
        # subsequent symbol does.
        increment = symbol_duration + (inter_char if chosen else 0.0)
        if cumulative + increment > duration_seconds:
            break
        chosen.append(next_symbol)
        cumulative += increment

    return GeneratedSequence(
        symbols=tuple(chosen),
        seed=seed,
        claimed_set=claimed_tuple,
    )
