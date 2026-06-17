"""HTTP API helpers for saved record list/read/delete endpoints."""

from __future__ import annotations

import json
import logging
import re
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from copy_653.config import load_save_directory
from copy_653.sequence.recognition_analysis import attach_recognition_review_analysis
from copy_653.session.compat import backfill_copy_key_record

logger = logging.getLogger(__name__)

HttpResponse = tuple[HTTPStatus, list[tuple[str, str]], bytes]

_KOCH_FILENAME_RE = re.compile(r"^[0-9A-Za-z._/-]+\.json$")
_CADENCE_FILENAME_RE = re.compile(r"^cadence-send-[0-9A-Za-z-]+\.json$")
_COPY_KEY_FILENAME_RE = re.compile(r"^copy-key-[0-9A-Za-z-]+\.json$")
_RECOGNITION_FILENAME_RE = re.compile(r"^[0-9A-Za-z._/-]+\.json$")
_RECORD_PATH_PART_RE = re.compile(r"^[0-9A-Za-z._-]+$")
_KEY_TRAINING_FILENAME_RE = re.compile(r"^[0-9A-Za-z._/-]+\.json$")


def _list_koch_exercises(config_path: Path | None) -> dict[str, Any]:
    return _list_records(
        config_path,
        subdirectory="koch-exercise",
        mode="koch-exercise",
        enrich=_enrich_koch_record,
        glob_pattern="*.json",
        relative_filenames=True,
    )


def _read_koch_exercise(config_path: Path | None, filename: str) -> HttpResponse:
    return _read_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_KOCH_FILENAME_RE,
        subdirectory="koch-exercise",
        mode="koch-exercise",
        allow_relative_filename=True,
    )


def _delete_koch_exercise(config_path: Path | None, filename: str) -> HttpResponse:
    return _delete_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_KOCH_FILENAME_RE,
        subdirectory="koch-exercise",
        mode="koch-exercise",
        allow_relative_filename=True,
    )


def _list_recognitions(config_path: Path | None) -> dict[str, Any]:
    return _list_records(
        config_path,
        subdirectory="recognition",
        mode="recognition",
        enrich=_enrich_recognition_record,
        glob_pattern="*.json",
        relative_filenames=True,
    )


def _read_recognition(config_path: Path | None, filename: str) -> HttpResponse:
    return _read_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_RECOGNITION_FILENAME_RE,
        subdirectory="recognition",
        mode="recognition",
        transform=attach_recognition_review_analysis,
        allow_relative_filename=True,
    )


def _delete_recognition(config_path: Path | None, filename: str) -> HttpResponse:
    return _delete_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_RECOGNITION_FILENAME_RE,
        subdirectory="recognition",
        mode="recognition",
        allow_relative_filename=True,
    )


def _list_cadence_sends(config_path: Path | None) -> dict[str, Any]:
    return _list_records(config_path, subdirectory="cadence-send", mode="cadence-send")


def _read_cadence_send(config_path: Path | None, filename: str) -> HttpResponse:
    return _read_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_CADENCE_FILENAME_RE,
        subdirectory="cadence-send",
        mode="cadence-send",
    )


def _delete_cadence_send(config_path: Path | None, filename: str) -> HttpResponse:
    return _delete_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_CADENCE_FILENAME_RE,
        subdirectory="cadence-send",
        mode="cadence-send",
    )


def _list_copy_key_sessions(config_path: Path | None) -> dict[str, Any]:
    return _list_records(config_path, subdirectory="copy-key", mode="copy-key")


def _read_copy_key_session(config_path: Path | None, filename: str) -> HttpResponse:
    return _read_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_COPY_KEY_FILENAME_RE,
        subdirectory="copy-key",
        mode="copy-key",
        transform=backfill_copy_key_record,
    )


def _delete_copy_key_session(config_path: Path | None, filename: str) -> HttpResponse:
    return _delete_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_COPY_KEY_FILENAME_RE,
        subdirectory="copy-key",
        mode="copy-key",
    )


def _enrich_key_training_record(data: dict[str, Any], entry: dict[str, Any]) -> None:
    """Add key-training-specific summary fields for the settings list."""
    entry["training_mode"] = data.get("training_mode") or "unknown"
    entry["session_status"] = data.get("session_status") or "unknown"
    attempts = data.get("attempts")
    sent = data.get("sent")
    key_events = data.get("key_events")
    entry["decoded_send_count"] = len(sent) if isinstance(sent, list) else 0
    entry["key_event_count"] = len(key_events) if isinstance(key_events, list) else 0
    if isinstance(attempts, list):
        entry["scored_event_count"] = len(attempts)
        entry["attempt_count"] = len(attempts)
        fault_counts: dict[str, int] = {}
        timing_fault_count = 0
        wrong_symbol_count = 0
        restart_count = 0
        completed_exercise_indexes: set[int] = set()
        exercise_summaries: dict[int, dict[str, int | bool]] = {}

        for a in attempts:
            exercise_index = a.get("exercise_index")
            if isinstance(exercise_index, int) and not isinstance(exercise_index, bool):
                summary = exercise_summaries.setdefault(
                    exercise_index,
                    {"faults": 0, "restarts": 0, "completed": False},
                )
            else:
                summary = None

            sym = a.get("target_symbol")
            result = a.get("result")
            if sym and result in ("timing-fail", "wrong-symbol"):
                fault_counts[sym] = fault_counts.get(sym, 0) + 1
                if summary is not None:
                    summary["faults"] = int(summary["faults"]) + 1
            if result == "timing-fail":
                timing_fault_count += 1
            elif result == "wrong-symbol":
                wrong_symbol_count += 1

            action = a.get("action")
            if action == "restart-line":
                restart_count += 1
                if summary is not None:
                    summary["restarts"] = int(summary["restarts"]) + 1
            elif action in {"complete-exercise", "complete-session"}:
                if isinstance(exercise_index, int) and not isinstance(exercise_index, bool):
                    completed_exercise_indexes.add(exercise_index)
                if summary is not None:
                    summary["completed"] = True

        entry["fault_counts"] = fault_counts
        entry["fault_count"] = timing_fault_count + wrong_symbol_count
        entry["timing_fault_count"] = timing_fault_count
        entry["wrong_symbol_count"] = wrong_symbol_count
        entry["restart_count"] = restart_count
        entry["completed_exercise_count"] = len(completed_exercise_indexes)
        entry["clean_exercise_count"] = sum(
            1
            for summary in exercise_summaries.values()
            if summary["completed"] and summary["faults"] == 0 and summary["restarts"] == 0
        )
        entry["repeated_exercise_count"] = sum(
            1 for summary in exercise_summaries.values() if int(summary["restarts"]) > 0
        )
        entry["exercise_attempt_count"] = sum(
            1 + int(summary["restarts"]) for summary in exercise_summaries.values()
        )
        if fault_counts:
            symbol, count = max(fault_counts.items(), key=lambda item: item[1])
            entry["hardest_symbol"] = symbol
            entry["hardest_symbol_faults"] = count
        else:
            entry["hardest_symbol"] = ""
            entry["hardest_symbol_faults"] = 0
    else:
        entry["scored_event_count"] = 0
        entry["attempt_count"] = 0
        entry["fault_counts"] = {}
        entry["fault_count"] = 0
        entry["timing_fault_count"] = 0
        entry["wrong_symbol_count"] = 0
        entry["restart_count"] = 0
        entry["completed_exercise_count"] = 0
        entry["clean_exercise_count"] = 0
        entry["repeated_exercise_count"] = 0
        entry["exercise_attempt_count"] = 0
        entry["hardest_symbol"] = ""
        entry["hardest_symbol_faults"] = 0


def _list_key_training_sessions(config_path: Path | None) -> dict[str, Any]:
    return _list_records(
        config_path,
        subdirectory="key-training",
        mode="key-training",
        enrich=_enrich_key_training_record,
        glob_pattern="*.json",
        relative_filenames=True,
    )


def _read_key_training_session(config_path: Path | None, filename: str) -> HttpResponse:
    return _read_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_KEY_TRAINING_FILENAME_RE,
        subdirectory="key-training",
        mode="key-training",
        allow_relative_filename=True,
    )


def _delete_key_training_session(config_path: Path | None, filename: str) -> HttpResponse:
    return _delete_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_KEY_TRAINING_FILENAME_RE,
        subdirectory="key-training",
        mode="key-training",
        allow_relative_filename=True,
    )


def _list_records(
    config_path: Path | None,
    *,
    subdirectory: str,
    mode: str,
    enrich: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    glob_pattern: str | None = None,
    relative_filenames: bool = False,
) -> dict[str, Any]:
    """List saved records of one type for the settings UI.

    Walks ``<save_dir>/<subdirectory>/<mode>-*.json``, filters by
    ``mode``, and returns a newest-first list of summary dicts.
    ``enrich``, when provided, receives ``(raw_data, summary_entry)``
    and may add mode-specific fields to the summary.
    """
    try:
        save_directory = load_save_directory(config_path)
    except Exception:
        logger.exception("could not resolve save_directory for %s listing", mode)
        return {"save_directory": "", "records": []}

    target_dir = save_directory / subdirectory
    records: list[dict[str, Any]] = []
    if target_dir.is_dir():
        for entry in sorted(target_dir.rglob(glob_pattern or f"{mode}-*.json")):
            try:
                data = json.loads(entry.read_text())
            except (OSError, ValueError):
                logger.exception("skipping unreadable %s record: %s", mode, entry)
                continue
            if data.get("mode") != mode:
                continue
            started_at = data.get("started_at")
            claimed_set = data.get("claimed_set")
            if not isinstance(started_at, str) or not isinstance(claimed_set, list):
                continue
            exercises = data.get("exercises")
            ended_at = data.get("ended_at")
            filename = (
                entry.relative_to(target_dir).as_posix() if relative_filenames else entry.name
            )
            record_entry: dict[str, Any] = {
                "filename": filename,
                "started_at": started_at,
                "ended_at": ended_at if isinstance(ended_at, str) else None,
                "claimed_set": [str(s) for s in claimed_set],
                "exercise_count": len(exercises) if isinstance(exercises, list) else 0,
            }
            if enrich is not None:
                enrich(data, record_entry)
            records.append(record_entry)

    records.sort(key=lambda r: r["started_at"], reverse=True)
    return {"save_directory": str(save_directory), "records": records}


def _read_record_file(
    *,
    config_path: Path | None,
    filename: str,
    filename_re: re.Pattern[str],
    subdirectory: str,
    mode: str,
    transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    allow_relative_filename: bool = False,
) -> HttpResponse:
    """Return the full JSON for one record file.

    Validates ``filename`` against ``filename_re``, resolves under
    ``<save_directory>/<subdirectory>/``, guards against path traversal,
    and returns the parsed JSON as a response. ``transform``, when
    provided, may mutate or replace the parsed dict before it is
    serialized (used for on-the-fly analysis backfill).
    """
    if not filename or not filename_re.fullmatch(filename):
        return _http_response(HTTPStatus.BAD_REQUEST, b"invalid filename")

    try:
        save_directory = load_save_directory(config_path)
    except Exception:
        logger.exception("could not resolve save_directory for %s read", mode)
        return _http_response(HTTPStatus.INTERNAL_SERVER_ERROR, b"save directory unavailable")

    target_dir = (save_directory / subdirectory).resolve()
    if allow_relative_filename:
        relative_path = _safe_relative_record_path(filename)
        if relative_path is None:
            return _http_response(HTTPStatus.BAD_REQUEST, b"invalid filename")
        resolved = (target_dir / relative_path).resolve()
        if not resolved.is_file():
            return _http_response(HTTPStatus.NOT_FOUND, b"not found")
    else:
        matches = sorted(target_dir.rglob(filename))
        if not matches:
            return _http_response(HTTPStatus.NOT_FOUND, b"not found")
        resolved = matches[0].resolve()
    try:
        resolved.relative_to(target_dir)
    except ValueError:
        return _http_response(HTTPStatus.NOT_FOUND, b"not found")

    try:
        data = json.loads(resolved.read_text())
    except (OSError, ValueError):
        logger.exception("failed to read %s record: %s", mode, resolved)
        return _http_response(HTTPStatus.INTERNAL_SERVER_ERROR, b"read failed")
    if not isinstance(data, dict) or data.get("mode") != mode:
        return _http_response(HTTPStatus.NOT_FOUND, b"not found")

    if transform is not None:
        data = transform(data)
    return _json_response(data)


def _delete_record_file(
    *,
    config_path: Path | None,
    filename: str,
    filename_re: re.Pattern[str],
    subdirectory: str,
    mode: str,
    allow_relative_filename: bool = False,
) -> HttpResponse:
    if not filename or not filename_re.fullmatch(filename):
        return _http_response(HTTPStatus.BAD_REQUEST, b"invalid filename")

    try:
        save_directory = load_save_directory(config_path)
    except Exception:
        logger.exception("could not resolve save_directory for %s delete", mode)
        return _http_response(HTTPStatus.INTERNAL_SERVER_ERROR, b"save directory unavailable")

    target_dir = (save_directory / subdirectory).resolve()
    if allow_relative_filename:
        relative_path = _safe_relative_record_path(filename)
        if relative_path is None:
            return _http_response(HTTPStatus.BAD_REQUEST, b"invalid filename")
        resolved = (target_dir / relative_path).resolve()
        if not resolved.is_file():
            return _http_response(HTTPStatus.NOT_FOUND, b"not found")
    else:
        matches = sorted(target_dir.rglob(filename))
        if not matches:
            return _http_response(HTTPStatus.NOT_FOUND, b"not found")
        resolved = matches[0].resolve()
    try:
        resolved.relative_to(target_dir)
    except ValueError:
        return _http_response(HTTPStatus.NOT_FOUND, b"not found")

    try:
        data = json.loads(resolved.read_text())
    except (OSError, ValueError):
        logger.exception("failed to validate %s record before delete: %s", mode, resolved)
        return _http_response(HTTPStatus.INTERNAL_SERVER_ERROR, b"read failed")
    if not isinstance(data, dict) or data.get("mode") != mode:
        return _http_response(HTTPStatus.NOT_FOUND, b"not found")

    try:
        resolved.unlink()
    except OSError:
        logger.exception("failed to delete %s record: %s", mode, resolved)
        return _http_response(HTTPStatus.INTERNAL_SERVER_ERROR, b"delete failed")

    return _json_response({"deleted": True, "filename": filename})


def _safe_relative_record_path(filename: str) -> Path | None:
    path = PurePosixPath(filename)
    if path.is_absolute() or not path.parts:
        return None
    if any(part in ("", ".", "..") for part in path.parts):
        return None
    if not all(_RECORD_PATH_PART_RE.fullmatch(part) for part in path.parts):
        return None
    return Path(*path.parts)


def _enrich_koch_record(data: dict[str, Any], entry: dict[str, Any]) -> None:
    if data.get("warm_up") is True:
        entry["warm_up"] = True
    generation = data.get("generation") or {}
    set_id = generation.get("set_id")
    if isinstance(set_id, str) and set_id:
        entry["set_id"] = set_id
    set_session = generation.get("set_session")
    if isinstance(set_session, int) and not isinstance(set_session, bool):
        entry["set_session"] = set_session


def _enrich_recognition_record(data: dict[str, Any], entry: dict[str, Any]) -> None:
    generation = data.get("generation") or {}
    set_id = generation.get("set_id")
    if isinstance(set_id, str) and set_id:
        entry["set_id"] = set_id
    set_session = generation.get("set_session")
    if isinstance(set_session, int) and not isinstance(set_session, bool):
        entry["set_session"] = set_session


def _http_response(status: HTTPStatus, body: bytes) -> HttpResponse:
    return (
        status,
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
        body,
    )


def _json_response(payload: dict[str, Any]) -> HttpResponse:
    body = json.dumps(payload).encode("utf-8")
    return (
        HTTPStatus.OK,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
        ],
        body,
    )
