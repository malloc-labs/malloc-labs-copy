"""HTTP API helpers for read-only record analytics endpoints."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from copy_653.config import load_save_directory
from copy_653.sequence.burden_analysis import (
    DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE,
    load_koch_attention_response,
    load_koch_burden_profile,
    load_recognition_attention_response,
    load_recognition_burden_profile,
)
from copy_653.sequence.cadence_analysis import (
    DEFAULT_EVIDENCE_WINDOW_SIZE as CADENCE_EVIDENCE_WINDOW_SIZE,
    load_band_evidence as load_cadence_band_evidence,
    load_band_history as load_cadence_band_history,
    record_claimed_set_key as cadence_record_claimed_set_key,
)
from copy_653.sequence.exercise_analysis import (
    DEFAULT_EVIDENCE_WINDOW_SIZE,
    load_band_evidence,
    load_band_history,
    load_confusion_pairs,
    record_claimed_set_key,
)
from copy_653.sequence.recognition_analysis import (
    load_recognition_confusion,
    load_recognition_timing,
)
from copy_653.server.records import (
    _iter_cadence_records,
    _iter_copy_key_records,
    _iter_koch_records,
    _iter_recognition_records,
)
from copy_653.session.compat import backfill_copy_key_records

logger = logging.getLogger(__name__)


def _read_koch_band_evidence(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
    window_size_raw: str | None,
) -> dict[str, Any]:
    try:
        save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_koch_records,
            extract_key=record_claimed_set_key,
            claimed_set_key=claimed_set_key,
        )
    except Exception:
        logger.exception("could not resolve save_directory for band-evidence read")
        return {
            "save_directory": "",
            "claimed_set_key": claimed_set_key or "",
            "session_count": 0,
            "window_size": DEFAULT_EVIDENCE_WINDOW_SIZE,
            "sessions_used": 0,
            "bands": [],
        }

    window_size = _parse_window_size(window_size_raw, DEFAULT_EVIDENCE_WINDOW_SIZE)
    evidence = load_band_evidence(records, claimed_set_key=resolved_key, window_size=window_size)
    evidence["save_directory"] = str(save_directory)
    return evidence


def _read_koch_band_history(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
) -> dict[str, Any]:
    try:
        save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_koch_records,
            extract_key=record_claimed_set_key,
            claimed_set_key=claimed_set_key,
        )
    except Exception:
        logger.exception("could not resolve save_directory for band-history read")
        return {
            "save_directory": "",
            "claimed_set_key": claimed_set_key or "",
            "session_count": 0,
            "sessions": [],
            "bands": [],
            "gear_changes": [],
            "current_gears": {},
        }

    history = load_band_history(records, claimed_set_key=resolved_key)
    history["save_directory"] = str(save_directory)
    return history


def _read_koch_confusion(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
) -> dict[str, Any]:
    try:
        _save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_koch_records,
            extract_key=record_claimed_set_key,
            claimed_set_key=claimed_set_key,
        )
    except Exception:
        logger.exception("could not resolve save_directory for confusion read")
        return {
            "claimed_set_key": claimed_set_key or "",
            "exercises_used": 0,
            "substitutions": [],
        }

    return load_confusion_pairs(records, claimed_set_key=resolved_key)


def _read_koch_burden_profile(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
    window_size_raw: str | None,
) -> dict[str, Any]:
    try:
        _save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_koch_records,
            extract_key=record_claimed_set_key,
            claimed_set_key=claimed_set_key,
        )
    except Exception:
        logger.exception("could not resolve save_directory for Koch burden profile read")
        return {
            "version": "burden-profile-v1",
            "claimed_set_key": claimed_set_key or "",
            "record_count": 0,
            "records_used": 0,
            "burdens": {},
        }

    window_size = _parse_window_size(window_size_raw, DEFAULT_EVIDENCE_WINDOW_SIZE)
    return load_koch_burden_profile(
        records,
        claimed_set_key=resolved_key,
        window_size=window_size,
    )


def _read_koch_attention_response(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
    window_size_raw: str | None,
) -> dict[str, Any]:
    try:
        _save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_koch_records,
            extract_key=record_claimed_set_key,
            claimed_set_key=claimed_set_key,
        )
    except Exception:
        logger.exception("could not resolve save_directory for Koch attention response read")
        return {
            "version": "attention-response-v1",
            "claimed_set_key": claimed_set_key or "",
            "record_count": 0,
            "records_used": 0,
            "exercise_count": 0,
            "conditions": [],
        }

    window_size = _parse_window_size(window_size_raw, DEFAULT_EVIDENCE_WINDOW_SIZE)
    return load_koch_attention_response(
        records,
        claimed_set_key=resolved_key,
        window_size=window_size,
    )


def _read_recognition_confusion(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
) -> dict[str, Any]:
    try:
        _save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_recognition_records,
            extract_key=record_claimed_set_key,
            claimed_set_key=claimed_set_key,
        )
    except Exception:
        logger.exception("could not resolve save_directory for recognition confusion read")
        return {
            "claimed_set_key": claimed_set_key or "",
            "exercises_used": 0,
            "committed_substitutions": [],
            "caught_substitutions": [],
        }

    return load_recognition_confusion(records, claimed_set_key=resolved_key)


def _read_recognition_timing(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
) -> dict[str, Any]:
    try:
        _save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_recognition_records,
            extract_key=record_claimed_set_key,
            claimed_set_key=claimed_set_key,
        )
    except Exception:
        logger.exception("could not resolve save_directory for recognition timing read")
        return {
            "claimed_set_key": claimed_set_key or "",
            "exercises_used": 0,
            "targets": [],
        }

    return load_recognition_timing(records, claimed_set_key=resolved_key)


def _read_recognition_burden_profile(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
    window_size_raw: str | None,
) -> dict[str, Any]:
    try:
        _save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_recognition_and_koch_records,
            extract_key=record_claimed_set_key,
            claimed_set_key=claimed_set_key,
        )
    except Exception:
        logger.exception("could not resolve save_directory for recognition burden profile read")
        return {
            "version": "burden-profile-v1",
            "claimed_set_key": claimed_set_key or "",
            "record_count": 0,
            "records_used": 0,
            "burdens": {},
        }

    window_size = _parse_window_size(window_size_raw, DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE)
    return load_recognition_burden_profile(
        records,
        claimed_set_key=resolved_key,
        window_size=window_size,
    )


def _read_recognition_attention_response(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
    window_size_raw: str | None,
) -> dict[str, Any]:
    try:
        _save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_recognition_records,
            extract_key=record_claimed_set_key,
            claimed_set_key=claimed_set_key,
        )
    except Exception:
        logger.exception("could not resolve save_directory for recognition attention response read")
        return {
            "version": "attention-response-v1",
            "claimed_set_key": claimed_set_key or "",
            "record_count": 0,
            "records_used": 0,
            "exercise_count": 0,
            "conditions": [],
        }

    window_size = _parse_window_size(window_size_raw, DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE)
    return load_recognition_attention_response(
        records,
        claimed_set_key=resolved_key,
        window_size=window_size,
    )


def _read_cadence_band_evidence(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
    window_size_raw: str | None,
) -> dict[str, Any]:
    try:
        save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_cadence_records,
            extract_key=cadence_record_claimed_set_key,
            claimed_set_key=claimed_set_key,
        )
    except Exception:
        logger.exception("could not resolve save_directory for cadence evidence read")
        return {
            "save_directory": "",
            "claimed_set_key": claimed_set_key or "",
            "session_count": 0,
            "window_size": CADENCE_EVIDENCE_WINDOW_SIZE,
            "sessions_used": 0,
            "bands": [],
        }

    window_size = _parse_window_size(window_size_raw, CADENCE_EVIDENCE_WINDOW_SIZE)
    evidence = load_cadence_band_evidence(
        records, claimed_set_key=resolved_key, window_size=window_size
    )
    evidence["save_directory"] = str(save_directory)
    return evidence


def _read_cadence_band_history(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
) -> dict[str, Any]:
    try:
        save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_cadence_records,
            extract_key=cadence_record_claimed_set_key,
            claimed_set_key=claimed_set_key,
        )
    except Exception:
        logger.exception("could not resolve save_directory for cadence band-history read")
        return {
            "save_directory": "",
            "claimed_set_key": claimed_set_key or "",
            "session_count": 0,
            "sessions": [],
            "bands": [],
            "gear_changes": [],
            "current_gears": {},
        }

    history = load_cadence_band_history(records, claimed_set_key=resolved_key)
    history["save_directory"] = str(save_directory)
    return history


def _read_copy_key_band_evidence(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
    window_size_raw: str | None,
) -> dict[str, Any]:
    try:
        save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_copy_key_records,
            extract_key=cadence_record_claimed_set_key,
            claimed_set_key=claimed_set_key,
            transform=backfill_copy_key_records,
        )
    except Exception:
        logger.exception("could not resolve save_directory for copy-key evidence read")
        return {
            "save_directory": "",
            "claimed_set_key": claimed_set_key or "",
            "session_count": 0,
            "window_size": CADENCE_EVIDENCE_WINDOW_SIZE,
            "sessions_used": 0,
            "bands": [],
        }

    window_size = _parse_window_size(window_size_raw, CADENCE_EVIDENCE_WINDOW_SIZE)
    evidence = load_cadence_band_evidence(
        records, claimed_set_key=resolved_key, window_size=window_size, mode="copy-key"
    )
    evidence["save_directory"] = str(save_directory)
    return evidence


def _read_copy_key_band_history(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
) -> dict[str, Any]:
    try:
        save_directory, records, resolved_key = _resolve_records_and_key(
            config_path,
            iter_records=_iter_copy_key_records,
            extract_key=cadence_record_claimed_set_key,
            claimed_set_key=claimed_set_key,
            transform=backfill_copy_key_records,
        )
    except Exception:
        logger.exception("could not resolve save_directory for copy-key band-history read")
        return {
            "save_directory": "",
            "claimed_set_key": claimed_set_key or "",
            "session_count": 0,
            "sessions": [],
            "bands": [],
            "gear_changes": [],
            "current_gears": {},
        }

    history = load_cadence_band_history(records, claimed_set_key=resolved_key, mode="copy-key")
    history["save_directory"] = str(save_directory)
    return history


def _resolve_records_and_key(
    config_path: Path | None,
    *,
    iter_records: Callable[[Path], list[dict[str, Any]]],
    extract_key: Callable[[dict[str, Any]], str],
    claimed_set_key: str | None,
    transform: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
) -> tuple[Path, list[dict[str, Any]], str]:
    """Load records and resolve the claimed-set key for evidence/history endpoints."""
    save_directory = load_save_directory(config_path)
    records = iter_records(save_directory)
    if transform is not None:
        records = transform(records)
    resolved_key = claimed_set_key
    if not resolved_key:
        latest = max(
            records,
            key=lambda r: str(r.get("started_at") or ""),
            default=None,
        )
        resolved_key = extract_key(latest) if latest else ""
    return save_directory, records, resolved_key


def _iter_recognition_and_koch_records(save_directory: Path) -> list[dict[str, Any]]:
    """Load records needed for Recognition burden debt and transfer evidence."""
    return [
        *_iter_recognition_records(save_directory),
        *_iter_koch_records(save_directory),
    ]


def _parse_window_size(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
