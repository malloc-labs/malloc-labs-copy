"""Onset-window reconstruction for saved Symbol Recognition attempts."""

from __future__ import annotations

from typing import Any

ANALYSIS_VERSION = "recognition-analysis-v1"

# Per-slot outcome labels. ``caught_*`` outcomes carry one or more
# superseded tokens -- a false start the learner spoke before committing.
OUTCOME_CORRECT = "correct"
OUTCOME_SUBSTITUTION = "substitution"
OUTCOME_CAUGHT_CORRECT = "caught_correct"
OUTCOME_CAUGHT_SUBSTITUTION = "caught_substitution"
OUTCOME_MISS = "miss"


def window_exercise(
    symbols: list[dict[str, Any]],
    voice_capture: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reconstruct per-symbol responses for one recognition exercise."""
    ordered = _ordered_symbols(symbols)
    onsets = [float(entry["t_on"]) for entry in ordered]

    # Bucket utterances by the latest symbol whose t_on <= t. Index -1
    # is the pre-symbol bucket (arrived before anything played). Gear 2+
    # records may play a whole word/pair before the recognition window;
    # when a multi-token utterance lands after the final symbol in that
    # word, distribute those tokens across the word slots instead of
    # forcing them all onto the final symbol.
    buckets: dict[int, list[dict[str, Any]]] = {}
    pre_symbol: list[dict[str, Any]] = []
    for utterance in voice_capture:
        t = _utterance_time(utterance)
        slot = _latest_played_index(onsets, t)
        if slot < 0:
            pre_symbol.append(utterance)
        else:
            tokens = _utterance_symbols(utterance)
            distributed = _distribute_word_utterance(ordered, slot, tokens)
            if distributed:
                for target_slot, token in distributed:
                    split = dict(utterance)
                    split["symbols"] = [token]
                    buckets.setdefault(target_slot, []).append(split)
            else:
                buckets.setdefault(slot, []).append(utterance)

    slots: list[dict[str, Any]] = []
    committed_tokens: list[str] = []
    committed_confusions: list[list[str]] = []
    caught_confusions: list[list[str]] = []
    saw_miss = False
    saw_multi_token = False

    for index, entry in enumerate(ordered):
        truth = str(entry["symbol"])
        t_on = float(entry["t_on"])
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


def _distribute_word_utterance(
    ordered: list[dict[str, Any]],
    latest_slot: int,
    tokens: list[str],
) -> list[tuple[int, str]]:
    if len(tokens) <= 1:
        return []
    if latest_slot < 0 or latest_slot >= len(ordered):
        return []
    latest = ordered[latest_slot]
    word = latest.get("word")
    word_index = latest.get("word_index")
    if not isinstance(word, str) or len(word) <= 1:
        return []
    if not isinstance(word_index, int) or isinstance(word_index, bool):
        return []
    exercise_index = latest.get("exercise_index")
    word_slots = [
        idx
        for idx, entry in enumerate(ordered)
        if entry.get("exercise_index") == exercise_index
        and entry.get("word_index") == word_index
        and entry.get("word") == word
    ]
    if not word_slots or latest_slot != word_slots[-1]:
        return []
    if len(tokens) > len(word_slots):
        return []
    return list(zip(word_slots[: len(tokens)], tokens, strict=False))


def _ordered_symbols(symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return schedule entries sorted by onset, skipping malformed entries."""
    out: list[dict[str, Any]] = []
    for entry in symbols:
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("symbol")
        t_on = entry.get("t_on")
        if not isinstance(symbol, str) or not symbol:
            continue
        if not _is_number(t_on):
            continue
        clean = dict(entry)
        clean["symbol"] = symbol
        clean["t_on"] = float(t_on)
        out.append(clean)
    out.sort(key=lambda item: float(item["t_on"]))
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
