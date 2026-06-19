"""Adaptive key-training recommendations from saved structured sessions."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from copy_653.config import load_save_directory

logger = logging.getLogger(__name__)

RECENT_SESSION_LIMIT = 24
FOCUS_SYMBOL_LIMIT = 8
CONFUSION_LIMIT = 12

FAULT_WEIGHTS = {
    "timing-fail": 1.0,
    "wrong-symbol": 1.1,
    "invalid-pattern": 1.2,
}


def _read_key_training_records(
    config_path: Path | None,
) -> tuple[Path | None, list[dict[str, Any]]]:
    try:
        save_directory = load_save_directory(config_path)
    except Exception:
        logger.exception("could not resolve save_directory for key-training recommendations")
        return None, []

    target_dir = save_directory / "key-training"
    records: list[dict[str, Any]] = []
    if target_dir.is_dir():
        for entry in target_dir.rglob("*.json"):
            try:
                data = json.loads(entry.read_text())
            except (OSError, ValueError):
                logger.exception("skipping unreadable key-training record: %s", entry)
                continue
            if data.get("mode") == "key-training":
                records.append(data)

    records.sort(key=lambda rec: str(rec.get("started_at") or ""), reverse=True)
    return save_directory, records


def key_training_recommendations_response(config_path: Path | None) -> dict[str, Any]:
    save_directory, records = _read_key_training_records(config_path)
    payload = build_key_training_recommendations(records)
    payload["save_directory"] = str(save_directory) if save_directory is not None else ""
    return payload


def build_key_training_recommendations(records: list[dict[str, Any]]) -> dict[str, Any]:
    recent_records = records[:RECENT_SESSION_LIMIT]
    symbol_stats: dict[str, dict[str, float]] = {}
    pair_stats: dict[tuple[str, str], dict[str, float | str]] = {}
    sessions_with_evidence = 0
    attempt_count = 0

    for record_index, record in enumerate(recent_records):
        attempts = record.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            continue
        sessions_with_evidence += 1
        # Recent sessions should steer the next run, but older records still
        # contribute enough signal to avoid thrashing after one noisy session.
        recency_weight = max(0.25, 1.0 - (record_index * 0.035))
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            target = str(attempt.get("target_symbol") or "").strip()
            if not target:
                continue
            result = str(attempt.get("result") or "")
            action = str(attempt.get("action") or "")
            sent = str(attempt.get("sent_symbol") or "").strip()
            stats = symbol_stats.setdefault(
                target,
                {
                    "symbol": target,
                    "attempts": 0.0,
                    "accepted": 0.0,
                    "faults": 0.0,
                    "timing_faults": 0.0,
                    "wrong_symbols": 0.0,
                    "invalid_patterns": 0.0,
                    "restarts": 0.0,
                    "score": 0.0,
                },
            )
            attempt_count += 1
            stats["attempts"] += recency_weight
            if result == "accepted":
                stats["accepted"] += recency_weight
            elif result in FAULT_WEIGHTS:
                fault_weight = FAULT_WEIGHTS[result] * recency_weight
                stats["faults"] += recency_weight
                stats["score"] += fault_weight
                if result == "timing-fail":
                    stats["timing_faults"] += recency_weight
                elif result == "invalid-pattern":
                    stats["invalid_patterns"] += recency_weight
                elif result == "wrong-symbol":
                    stats["wrong_symbols"] += recency_weight
                    if sent:
                        pair_key = (target, sent)
                        pair = pair_stats.setdefault(
                            pair_key,
                            {
                                "target": target,
                                "sent": sent,
                                "count": 0.0,
                                "score": 0.0,
                            },
                        )
                        pair["count"] = float(pair["count"]) + recency_weight
                        pair["score"] = float(pair["score"]) + (1.1 * recency_weight)

            if action == "restart-line":
                stats["restarts"] += recency_weight
                stats["score"] += 0.7 * recency_weight

    focus_symbols = [_finalise_symbol_stats(stats) for stats in symbol_stats.values()]
    focus_symbols = [
        stats
        for stats in focus_symbols
        if stats["faults"] > 0 or stats["restarts"] > 0 or stats["score"] >= 0.35
    ]
    focus_symbols.sort(key=lambda stats: (-float(stats["score"]), str(stats["symbol"])))

    confusions = [
        {
            "target": str(pair["target"]),
            "sent": str(pair["sent"]),
            "count": round(float(pair["count"]), 3),
            "score": round(float(pair["score"]), 3),
        }
        for pair in pair_stats.values()
    ]
    confusions.sort(
        key=lambda pair: (-float(pair["score"]), str(pair["target"]), str(pair["sent"]))
    )

    return {
        "has_evidence": sessions_with_evidence > 0 and attempt_count > 0,
        "sessions_seen": len(records),
        "sessions_used": sessions_with_evidence,
        "attempt_count": attempt_count,
        "focus_symbols": focus_symbols[:FOCUS_SYMBOL_LIMIT],
        "confusions": confusions[:CONFUSION_LIMIT],
    }


def _finalise_symbol_stats(stats: dict[str, float]) -> dict[str, Any]:
    attempts = max(float(stats["attempts"]), 0.0)
    accepted = float(stats["accepted"])
    faults = float(stats["faults"])
    restarts = float(stats["restarts"])
    raw_score = float(stats["score"])
    exposure = math.log1p(attempts)
    score = raw_score + (faults * 0.2) + (restarts * 0.15) + exposure * min(1.0, faults)
    fault_rate = faults / attempts if attempts > 0 else 0.0
    clean_rate = accepted / attempts if attempts > 0 else 0.0
    return {
        "symbol": str(stats["symbol"]),
        "attempts": round(attempts, 3),
        "accepted": round(accepted, 3),
        "faults": round(faults, 3),
        "timing_faults": round(float(stats["timing_faults"]), 3),
        "wrong_symbols": round(float(stats["wrong_symbols"]), 3),
        "invalid_patterns": round(float(stats["invalid_patterns"]), 3),
        "restarts": round(restarts, 3),
        "fault_rate": round(fault_rate, 3),
        "clean_rate": round(clean_rate, 3),
        "score": round(score, 3),
    }
