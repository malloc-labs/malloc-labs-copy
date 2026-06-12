"""Scoring and text alignment for saved Koch Exercise answers."""

from __future__ import annotations

from math import log1p
import re
from typing import Any

from copy_653.sequence.copy_exercises import _score_copy_exercise

FIXED_LISTENING_ANCHOR = "DE"
ANALYSIS_VERSION = "koch-analysis-v1"

_SPACE_RE = re.compile(r"\s+")


def normalize_exercise_text(value: str) -> str:
    """Uppercase and collapse whitespace in an exercise or answer string."""
    return _SPACE_RE.sub(" ", value.strip().upper())


def strip_fixed_anchor(value: str) -> str:
    """Remove the fixed leading ``DE`` listening anchor if present."""
    normalized = normalize_exercise_text(value)
    if normalized == FIXED_LISTENING_ANCHOR:
        return ""
    prefix = f"{FIXED_LISTENING_ANCHOR} "
    if normalized.startswith(prefix):
        return normalized[len(prefix) :].strip()
    return normalized


def burden_score_for_exercise(played: str) -> int:
    """Return the abstract burden score for ``played`` excluding ``DE``."""
    core = strip_fixed_anchor(played)
    return _score_copy_exercise(core) if core else 0


def spacing_weight_for_claimed_set(claimed_set_size: int) -> float:
    """Spacing weight in [0.15, 0.5] decreasing with claimed-set size."""
    if claimed_set_size <= 0:
        return 0.5
    return max(0.15, min(0.5, 1.0 / claimed_set_size))


def analyse_answer(
    *,
    played: str,
    answer: str,
    exercise_index: int,
    burden_score: int,
    burden_band: int,
    gear: int,
    claimed_set_size: int,
    repeat_weight: float = 1.0,
) -> dict[str, Any]:
    """Compare one saved answer to one played exercise."""
    core = strip_fixed_anchor(played)
    answer_core = strip_fixed_anchor(answer)
    symbol_truth = _symbols_only(core)
    symbol_answer = _symbols_only(answer_core)
    symbol_available = max(len(symbol_truth), len(symbol_answer))
    symbol_distance = _levenshtein(symbol_truth, symbol_answer)
    symbol_correct = max(0, symbol_available - symbol_distance)

    truth_boundaries = _word_boundaries(core)
    answer_boundaries = _word_boundaries(answer_core)
    spacing_available = max(len(truth_boundaries), len(answer_boundaries))
    spacing_correct = len(truth_boundaries & answer_boundaries)

    symbol_fraction = _fraction(symbol_correct, symbol_available)
    spacing_weight = spacing_weight_for_claimed_set(claimed_set_size)
    if spacing_available > 0:
        spacing_fraction = _fraction(spacing_correct, spacing_available)
        combined = ((1.0 - spacing_weight) * symbol_fraction) + (spacing_weight * spacing_fraction)
    else:
        # Single-word exercise: no boundary evidence exists, so use symbol evidence alone.
        spacing_fraction = 1.0
        combined = symbol_fraction
    bounded_repeat_weight = min(1.0, max(0.0, repeat_weight))
    burden_weight = 1.0 + log1p(max(0, burden_score))
    position_weight = 1.0 + ((max(1, exercise_index) - 1) * 0.10)
    evidence = combined * burden_weight * position_weight * bounded_repeat_weight

    return {
        "version": ANALYSIS_VERSION,
        "saved": True,
        "normalized_answer": normalize_exercise_text(answer),
        "answer_core": answer_core,
        "symbol_correct_units": symbol_correct,
        "symbol_available_units": symbol_available,
        "symbol_edit_distance": symbol_distance,
        "spacing_correct_units": spacing_correct,
        "spacing_available_units": spacing_available,
        "spacing_weight": round(spacing_weight, 3),
        "claimed_set_size": claimed_set_size,
        "repeat_weight": round(bounded_repeat_weight, 3),
        "combined_fraction": round(combined, 6),
        "evidence": round(evidence, 6),
        "band_state": _band_state(combined),
        "burden_band": burden_band,
        "gear": gear,
    }


def _symbols_only(value: str) -> str:
    return normalize_exercise_text(value).replace(" ", "")


def _word_boundaries(value: str) -> set[int]:
    words = [word for word in normalize_exercise_text(value).split(" ") if word]
    boundaries: set[int] = set()
    cursor = 0
    for word in words[:-1]:
        cursor += len(word)
        boundaries.add(cursor)
    return boundaries


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, lch in enumerate(left, start=1):
        current = [i]
        for j, rch in enumerate(right, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (0 if lch == rch else 1)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def _align(truth: str, answer: str) -> list[tuple[str, str | None, str | None]]:
    """Levenshtein backtrace returning per-position edit operations."""
    n, m = len(truth), len(answer)
    if n == 0:
        return [("ins", None, ch) for ch in answer]
    if m == 0:
        return [("del", ch, None) for ch in truth]

    matrix = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        matrix[i][0] = i
    for j in range(m + 1):
        matrix[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if truth[i - 1] == answer[j - 1] else 1
            matrix[i][j] = min(
                matrix[i - 1][j] + 1,
                matrix[i][j - 1] + 1,
                matrix[i - 1][j - 1] + cost,
            )

    ops: list[tuple[str, str | None, str | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            cost = 0 if truth[i - 1] == answer[j - 1] else 1
            if matrix[i][j] == matrix[i - 1][j - 1] + cost:
                if cost == 0:
                    ops.append(("match", truth[i - 1], answer[j - 1]))
                else:
                    ops.append(("sub", truth[i - 1], answer[j - 1]))
                i -= 1
                j -= 1
                continue
        if i > 0 and matrix[i][j] == matrix[i - 1][j] + 1:
            ops.append(("del", truth[i - 1], None))
            i -= 1
        else:
            ops.append(("ins", None, answer[j - 1]))
            j -= 1
    ops.reverse()
    return ops


def _fraction(correct: int, available: int, *, default: float = 0.0) -> float:
    if available <= 0:
        return default
    return max(0.0, min(1.0, correct / available))


def _band_state(value: float) -> str:
    if value < 0.70:
        return "low"
    if value < 0.85:
        return "building"
    if value < 0.95:
        return "steady"
    if value < 1.0:
        return "strong"
    return "exact"


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _repeat_weight(occurrence: int) -> float:
    if occurrence <= 1:
        return 1.0
    if occurrence == 2:
        return 0.7
    if occurrence == 3:
        return 0.5
    return 0.35
