"""Tests for copy_653.sequence.generator."""

from __future__ import annotations

import random

import pytest

from copy_653 import sequence
from copy_653.audio import patterns, synth, timing
from copy_653.audio.parameters import AudioParameters

# A fast, no-Farnsworth params block keeps the tests' generated
# sequences cheap. The numbers don't matter except that all symbols
# in KOCH_FIRST_PAIR fit within the requested durations.
FAST_PARAMS = AudioParameters(character_speed_wpm=25, effective_speed_wpm=25)


def test_generate_uses_only_claimed_symbols():
    seq = sequence.generate(
        claimed_set=patterns.KOCH_FIRST_PAIR,
        duration_seconds=10.0,
        params=FAST_PARAMS,
        seed=42,
    )
    assert len(seq.symbols) > 0
    for s in seq.symbols:
        assert s in patterns.KOCH_FIRST_PAIR


def test_same_seed_reproduces_sequence():
    a = sequence.generate(
        claimed_set=patterns.KOCH_FIRST_PAIR,
        duration_seconds=10.0,
        params=FAST_PARAMS,
        seed=42,
    )
    b = sequence.generate(
        claimed_set=patterns.KOCH_FIRST_PAIR,
        duration_seconds=10.0,
        params=FAST_PARAMS,
        seed=42,
    )
    # Spec §2.8: the seed is recorded so the learner can replay the
    # same stream by re-running with the same seed.
    assert a.symbols == b.symbols
    assert a.seed == b.seed == 42
    assert a.claimed_set == b.claimed_set


def test_different_seeds_produce_different_sequences():
    # 10 seconds at 25 WPM gives ~14 symbols. Probability of identical
    # sequences across two different seeds is roughly 2^-14 ≈ 6e-5.
    a = sequence.generate(
        claimed_set=patterns.KOCH_FIRST_PAIR,
        duration_seconds=10.0,
        params=FAST_PARAMS,
        seed=1,
    )
    b = sequence.generate(
        claimed_set=patterns.KOCH_FIRST_PAIR,
        duration_seconds=10.0,
        params=FAST_PARAMS,
        seed=2,
    )
    assert a.symbols != b.symbols


def test_no_seed_yields_concrete_recordable_seed():
    # Spec §2.8: the seed is recorded in the session record. So even
    # when the caller does not supply one, the result must carry one.
    seq = sequence.generate(
        claimed_set=patterns.KOCH_FIRST_PAIR,
        duration_seconds=5.0,
        params=FAST_PARAMS,
    )
    assert isinstance(seq.seed, int)
    assert seq.seed >= 0
    # And replaying with that seed reproduces the same stream.
    replay = sequence.generate(
        claimed_set=patterns.KOCH_FIRST_PAIR,
        duration_seconds=5.0,
        params=FAST_PARAMS,
        seed=seq.seed,
    )
    assert replay.symbols == seq.symbols


def test_module_level_random_is_not_perturbed():
    # Spec §2.8: "The module-level random state is never modified.
    # Other libraries in the engine process are not affected by
    # Copy's sequence generation."
    random.seed(123)
    expected = random.random()

    random.seed(123)
    sequence.generate(
        claimed_set=patterns.KOCH_FIRST_PAIR,
        duration_seconds=10.0,
        params=FAST_PARAMS,
        seed=999,
    )
    actual_after_generate = random.random()

    assert actual_after_generate == expected


def test_total_duration_does_not_exceed_target():
    target = 5.0
    seq = sequence.generate(
        claimed_set=patterns.KOCH_FIRST_PAIR,
        duration_seconds=target,
        params=FAST_PARAMS,
        seed=42,
    )
    timeline = synth.compute_timeline(list(seq.symbols), FAST_PARAMS)
    assert timeline  # non-empty for this duration
    _, _, last_t_off = timeline[-1]
    assert last_t_off <= target


def test_total_duration_close_to_target():
    # The realised stream should sit within one (longest-symbol +
    # inter-char) of the target — strict uniform sampling stops on
    # the first draw that would overshoot, so the under-shoot is
    # bounded by the largest possible increment.
    target = 30.0
    seq = sequence.generate(
        claimed_set=patterns.KOCH_FIRST_PAIR,
        duration_seconds=target,
        params=FAST_PARAMS,
        seed=42,
    )
    timeline = synth.compute_timeline(list(seq.symbols), FAST_PARAMS)
    _, _, last_t_off = timeline[-1]
    longest_inc = max(
        synth.symbol_duration_seconds(s, FAST_PARAMS) for s in patterns.KOCH_FIRST_PAIR
    ) + timing.inter_character_seconds(FAST_PARAMS)
    assert last_t_off >= target - longest_inc


def test_duration_too_short_for_any_symbol_returns_empty_with_seed():
    # Sub-millisecond target — no symbol fits.
    seq = sequence.generate(
        claimed_set=patterns.KOCH_FIRST_PAIR,
        duration_seconds=0.001,
        params=FAST_PARAMS,
    )
    assert seq.symbols == ()
    # Seed is still recorded — empty is a valid outcome, not an error.
    assert isinstance(seq.seed, int)


def test_uniform_smoke_over_long_run():
    # Loose check: a long run from a uniform K/M sampler should not
    # produce a wildly skewed split. Not a statistical assertion;
    # tightening this risks flakiness.
    seq = sequence.generate(
        claimed_set=patterns.KOCH_FIRST_PAIR,
        duration_seconds=120.0,
        params=FAST_PARAMS,
        seed=42,
    )
    counts = {s: seq.symbols.count(s) for s in patterns.KOCH_FIRST_PAIR}
    total = sum(counts.values())
    assert total > 50, "expected many symbols in a 2-minute run"
    for s, c in counts.items():
        assert 0.3 < c / total < 0.7, f"{s} fraction {c}/{total}"


def test_claimed_set_preserves_order_in_record():
    # claimed_set is recorded in caller-supplied order so the session
    # record is deterministic from the caller's perspective.
    seq = sequence.generate(
        claimed_set=("M", "K"),
        duration_seconds=5.0,
        params=FAST_PARAMS,
        seed=1,
    )
    assert seq.claimed_set == ("M", "K")


def test_empty_claimed_set_raises():
    with pytest.raises(ValueError, match="claimed_set must be non-empty"):
        sequence.generate(
            claimed_set=(),
            duration_seconds=10.0,
            params=FAST_PARAMS,
        )


def test_duplicate_in_claimed_set_raises():
    with pytest.raises(ValueError, match="duplicates"):
        sequence.generate(
            claimed_set=("K", "K", "M"),
            duration_seconds=10.0,
            params=FAST_PARAMS,
        )


def test_non_positive_duration_raises():
    with pytest.raises(ValueError, match="duration_seconds"):
        sequence.generate(
            claimed_set=patterns.KOCH_FIRST_PAIR,
            duration_seconds=0.0,
            params=FAST_PARAMS,
        )
    with pytest.raises(ValueError, match="duration_seconds"):
        sequence.generate(
            claimed_set=patterns.KOCH_FIRST_PAIR,
            duration_seconds=-1.0,
            params=FAST_PARAMS,
        )


def test_unknown_symbol_in_claimed_set_raises_value_error():
    # We surface unknown symbols as ValueError so the failure shape is
    # consistent with the other input validation; the underlying
    # KeyError from patterns.pattern_for is wrapped.
    with pytest.raises(ValueError, match="unknown symbol"):
        sequence.generate(
            claimed_set=("K", "!"),
            duration_seconds=10.0,
            params=FAST_PARAMS,
        )
