"""Windowing + classification for saved Symbol Recognition attempts.

Like :mod:`copy_653.sequence.exercise_analysis`, this module produces
backend evidence — not learner-facing feedback, scores, or progress
metrics (spec §9). It is the bottom layer of the recognition evidence
pipeline: it takes the raw, honest record (the played ``symbols``
schedule and the per-exercise ``voice_capture``) and reconstructs, per
played symbol, what the learner actually committed and what they said
on the way there.

The point of difference from the Koch path is timing. A typed Koch
answer is a flat string, so confusion there can only be recovered by
string alignment (:func:`exercise_analysis.load_confusion_pairs`). A
recognition attempt carries a timestamp on every utterance, which lets
us align responses to the cadence rather than to each other — and that
is what makes a *self-correction* visible. When a learner hears U,
starts to say "romeo", catches it, and lands on "uniform" in one
breath, the recogniser honestly records "romeo uniform". Flat string
alignment would treat the stray R as an insertion and discard it;
here we keep it, label it, and route it to a separate stream so a
caught confusion never counts as a committed one.

Nothing is mutated and nothing is collapsed. ``voice_capture`` stays
the verbatim record of what was said; this module only *derives* a view
over it.
"""

from __future__ import annotations

from typing import Any

ANALYSIS_VERSION = "recognition-analysis-v1"

# Per-slot outcome labels. ``caught_*`` outcomes carry one or more
# superseded tokens — a false start the learner spoke before committing.
OUTCOME_CORRECT = "correct"
OUTCOME_SUBSTITUTION = "substitution"
OUTCOME_CAUGHT_CORRECT = "caught_correct"
OUTCOME_CAUGHT_SUBSTITUTION = "caught_substitution"
OUTCOME_MISS = "miss"


def window_exercise(
    symbols: list[dict[str, Any]],
    voice_capture: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reconstruct per-symbol responses for one recognition exercise.

    ``symbols`` is the played truth schedule for a single exercise —
    each entry an ``{"symbol", "t_on", ...}`` dict, in play order.
    ``voice_capture`` is that exercise's list of recogniser finals —
    each an ``{"text", "symbols", "t"}`` dict, where ``symbols`` is the
    already-tokenised list and ``t`` is seconds since session start.

    Each utterance is attached to the *latest symbol already played* —
    the last symbol whose ``t_on`` is at or before the utterance time.
    With the ``say_after`` flow a response always lands in the window
    that opens when its symbol plays and closes when the next one does;
    the final symbol's window runs to the end. Utterances that arrive
    before the first symbol plays cannot be a response to anything and
    are surfaced in ``pre_symbol`` rather than forced onto slot 1.

    Within a window the tokens are taken in chronological order; the
    last token is what the learner *committed*, everything before it is
    *superseded*. The committed tokens, joined, are the answer that a
    fraction/evidence layer should align against truth — corrections
    no longer inflate its length.

    The returned dict carries, per exercise: ``committed_answer``, the
    two confusion streams (``committed_confusions`` and
    ``caught_confusions``, never merged), an ``ambiguous_lag`` flag (set
    when an empty window and a multi-token window coexist, i.e. the
    learner may have fallen behind rather than self-corrected — the
    per-slot labels are unreliable in that case and the next layer
    should treat them with care), ``pre_symbol``, and the per-symbol
    ``slots``.
    """
    ordered = _ordered_symbols(symbols)
    onsets = [t_on for _, t_on in ordered]

    # Bucket utterances by the latest symbol whose t_on <= t. Index -1
    # is the pre-symbol bucket (arrived before anything played).
    buckets: dict[int, list[dict[str, Any]]] = {}
    pre_symbol: list[dict[str, Any]] = []
    for utterance in voice_capture:
        t = _utterance_time(utterance)
        slot = _latest_played_index(onsets, t)
        if slot < 0:
            pre_symbol.append(utterance)
        else:
            buckets.setdefault(slot, []).append(utterance)

    slots: list[dict[str, Any]] = []
    committed_tokens: list[str] = []
    committed_confusions: list[list[str]] = []
    caught_confusions: list[list[str]] = []
    saw_miss = False
    saw_multi_token = False

    for index, (truth, t_on) in enumerate(ordered):
        utterances = buckets.get(index, [])
        utterances.sort(key=_utterance_time)
        tokens = [tok for utterance in utterances for tok in _utterance_symbols(utterance)]

        committed = tokens[-1] if tokens else None
        superseded = tokens[:-1]

        if committed is not None:
            committed_tokens.append(committed)
        if len(tokens) > 1:
            saw_multi_token = True

        outcome = _classify(truth, committed, superseded)
        if outcome == OUTCOME_MISS:
            saw_miss = True

        if committed is not None and committed != truth:
            committed_confusions.append([truth, committed])
        for token in superseded:
            if token != truth:
                caught_confusions.append([truth, token])

        slots.append(
            {
                "index": index + 1,
                "truth": truth,
                "t_on": t_on,
                "tokens": tokens,
                "committed": committed,
                "superseded": superseded,
                "outcome": outcome,
                "utterances": utterances,
            }
        )

    return {
        "version": ANALYSIS_VERSION,
        "committed_answer": "".join(committed_tokens),
        "committed_confusions": committed_confusions,
        "caught_confusions": caught_confusions,
        "ambiguous_lag": saw_miss and saw_multi_token,
        "pre_symbol": pre_symbol,
        "slots": slots,
    }


def _classify(truth: str, committed: str | None, superseded: list[str]) -> str:
    if committed is None:
        return OUTCOME_MISS
    if superseded:
        return OUTCOME_CAUGHT_CORRECT if committed == truth else OUTCOME_CAUGHT_SUBSTITUTION
    return OUTCOME_CORRECT if committed == truth else OUTCOME_SUBSTITUTION


def _ordered_symbols(symbols: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """Return ``[(symbol, t_on), ...]`` sorted by onset.

    Entries without a usable symbol or numeric ``t_on`` are skipped — a
    malformed schedule should not crash the loader (spec §1.5 is about
    config; here a defensive skip keeps derived evidence honest).
    """
    out: list[tuple[str, float]] = []
    for entry in symbols:
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("symbol")
        t_on = entry.get("t_on")
        if not isinstance(symbol, str) or not symbol:
            continue
        if not _is_number(t_on):
            continue
        out.append((symbol, float(t_on)))
    out.sort(key=lambda pair: pair[1])
    return out


def _latest_played_index(onsets: list[float], t: float) -> int:
    """Index of the last onset that is <= ``t``; -1 if ``t`` precedes all."""
    slot = -1
    for index, onset in enumerate(onsets):
        if onset <= t:
            slot = index
        else:
            break
    return slot


def _utterance_time(utterance: dict[str, Any]) -> float:
    t = utterance.get("t") if isinstance(utterance, dict) else None
    return float(t) if _is_number(t) else 0.0


def _utterance_symbols(utterance: dict[str, Any]) -> list[str]:
    if not isinstance(utterance, dict):
        return []
    raw = utterance.get("symbols")
    if not isinstance(raw, list):
        return []
    return [tok for tok in raw if isinstance(tok, str) and tok]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
