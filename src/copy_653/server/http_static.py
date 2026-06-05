"""Static HTTP surface served alongside the WebSocket endpoint.

Spec §1.4: the engine and UI live on one TCP port; non-WS requests
are answered as plain HTTP from the ``web/`` directory. Everything
in this module is pure — no engine state crosses the seam.
"""

from __future__ import annotations

import io
import json
import logging
import mimetypes
import re
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from websockets.datastructures import Headers

from copy_653 import __version__
from copy_653.config import load_save_directory
from copy_653.sequence.exercise_analysis import (
    DEFAULT_EVIDENCE_WINDOW_SIZE,
    load_band_evidence,
    load_band_history,
    load_confusion_pairs,
    record_claimed_set_key,
)
from copy_653.sequence.cadence_analysis import (
    DEFAULT_EVIDENCE_WINDOW_SIZE as CADENCE_EVIDENCE_WINDOW_SIZE,
    load_band_evidence as load_cadence_band_evidence,
    load_band_history as load_cadence_band_history,
    record_claimed_set_key as cadence_record_claimed_set_key,
)
from copy_653.sequence.recognition_analysis import (
    attach_recognition_review_analysis,
    load_recognition_confusion,
    load_recognition_timing,
)
from copy_653.sequence.burden_analysis import (
    DEFAULT_RECOGNITION_BURDEN_WINDOW_SIZE,
    load_koch_attention_response,
    load_koch_burden_profile,
    load_recognition_attention_response,
    load_recognition_burden_profile,
)
from copy_653.server.records import (
    _iter_cadence_records,
    _iter_copy_key_records,
    _iter_koch_records,
    _iter_recognition_records,
)
from copy_653.server.voice_api import voice_lexicon_response, voice_status_response
from copy_653.session.compat import backfill_copy_key_record, backfill_copy_key_records

logger = logging.getLogger(__name__)

HttpResponse = tuple[HTTPStatus, list[tuple[str, str]], bytes]
ApiHandler = Callable[[dict[str, list[str]], Path | None], HttpResponse]


def find_web_root() -> Path:
    """Locate the ``web/`` directory by walking up from this file.

    Works for editable installs (``pip install -e .``), which is the v0
    distribution shape (spec §11.1). A future packaged install would
    need ``importlib.resources`` and a ``web/`` bundled into the
    package; that is not v0.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "web"
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate
    raise RuntimeError(
        f"Could not locate web/ relative to {here}. "
        "v0 expects an editable install layout (spec §11.1)."
    )


def _build_static_handler(web_root: Path, config_path: Path | None = None):
    """Return a ``process_request`` callable bound to ``web_root``.

    The callable is what websockets invokes for every incoming HTTP
    request before deciding whether to upgrade to WS. Returning
    ``None`` lets the WS handshake proceed; returning a 3-tuple
    answers the request as plain HTTP.

    ``config_path`` is read fresh on each API call that needs the
    learner's save directory (spec §6.3) — no caching, so a learner
    who edits ``config.toml`` sees the change on the next request.
    """

    async def process_request(
        path: str, request_headers: Headers
    ) -> tuple[HTTPStatus, list[tuple[str, str]], bytes] | None:
        """Serve static HTTP requests or allow the WebSocket upgrade."""
        parsed_path = urlsplit(path)
        clean_path = parsed_path.path

        # Allow WS upgrades for the main JSON action protocol and for
        # the binary-PCM voice endpoint. Any other path falls through
        # to API dispatch and then static-file lookup.
        if clean_path in ("/ws", "/voice/ws"):
            return None

        api_response = _handle_api_request(clean_path, parsed_path.query, config_path)
        if api_response is not None:
            return api_response

        target = "index.html" if clean_path == "/" else clean_path.lstrip("/")
        resolved = (web_root / target).resolve()

        try:
            resolved.relative_to(web_root)
        except ValueError:
            return _http_response(HTTPStatus.NOT_FOUND, b"not found")

        if not resolved.is_file():
            return _http_response(HTTPStatus.NOT_FOUND, b"not found")

        body = resolved.read_bytes()
        mime, _ = mimetypes.guess_type(resolved.name)
        content_type = mime or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type = f"{content_type}; charset=utf-8"

        return (
            HTTPStatus.OK,
            [
                ("Content-Type", content_type),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ],
            body,
        )

    return process_request


# ---------------------------------------------------------------------------
# API dispatch helpers
# ---------------------------------------------------------------------------


def _handle_api_request(
    clean_path: str, query: str, config_path: Path | None
) -> HttpResponse | None:
    handler = _API_ROUTES.get(clean_path)
    if handler is None:
        return None
    return handler(parse_qs(query), config_path)


def _first_query_value(params: dict[str, list[str]], *names: str) -> str:
    for name in names:
        values = params.get(name) or []
        if values:
            return values[0]
    return ""


def _optional_query_value(params: dict[str, list[str]], name: str) -> str | None:
    return _first_query_value(params, name) or None


def _api_version(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _json_response({"version": __version__})


def _api_koch_exercises(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _json_response(_list_koch_exercises(config_path))


def _api_koch_exercise(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _read_koch_exercise(config_path, _first_query_value(params, "file", "filename"))


def _api_delete_koch_exercise(
    params: dict[str, list[str]], config_path: Path | None
) -> HttpResponse:
    return _delete_koch_exercise(config_path, _first_query_value(params, "file", "filename"))


def _api_koch_band_evidence(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _json_response(
        _read_koch_band_evidence(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
            window_size_raw=_optional_query_value(params, "window_size"),
        )
    )


def _api_koch_band_history(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _json_response(
        _read_koch_band_history(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
        )
    )


def _api_koch_burden_profile(
    params: dict[str, list[str]], config_path: Path | None
) -> HttpResponse:
    return _json_response(
        _read_koch_burden_profile(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
            window_size_raw=_optional_query_value(params, "window_size"),
        )
    )


def _api_koch_attention_response(
    params: dict[str, list[str]], config_path: Path | None
) -> HttpResponse:
    return _json_response(
        _read_koch_attention_response(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
            window_size_raw=_optional_query_value(params, "window_size"),
        )
    )


def _api_koch_confusion(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _json_response(
        _read_koch_confusion(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
        )
    )


def _api_recognition_confusion(
    params: dict[str, list[str]], config_path: Path | None
) -> HttpResponse:
    return _json_response(
        _read_recognition_confusion(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
        )
    )


def _api_recognition_timing(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _json_response(
        _read_recognition_timing(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
        )
    )


def _api_recognition_burden_profile(
    params: dict[str, list[str]], config_path: Path | None
) -> HttpResponse:
    return _json_response(
        _read_recognition_burden_profile(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
            window_size_raw=_optional_query_value(params, "window_size"),
        )
    )


def _api_recognition_attention_response(
    params: dict[str, list[str]], config_path: Path | None
) -> HttpResponse:
    return _json_response(
        _read_recognition_attention_response(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
            window_size_raw=_optional_query_value(params, "window_size"),
        )
    )


def _api_recognitions(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _json_response(_list_recognitions(config_path))


def _api_recognition(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _read_recognition(config_path, _first_query_value(params, "file", "filename"))


def _api_delete_recognition(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _delete_recognition(config_path, _first_query_value(params, "file", "filename"))


def _api_cadence_sends(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _json_response(_list_cadence_sends(config_path))


def _api_cadence_send(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _read_cadence_send(config_path, _first_query_value(params, "file", "filename"))


def _api_delete_cadence_send(
    params: dict[str, list[str]], config_path: Path | None
) -> HttpResponse:
    return _delete_cadence_send(config_path, _first_query_value(params, "file", "filename"))


def _api_cadence_band_evidence(
    params: dict[str, list[str]], config_path: Path | None
) -> HttpResponse:
    return _json_response(
        _read_cadence_band_evidence(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
            window_size_raw=_optional_query_value(params, "window_size"),
        )
    )


def _api_cadence_band_history(
    params: dict[str, list[str]], config_path: Path | None
) -> HttpResponse:
    return _json_response(
        _read_cadence_band_history(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
        )
    )


def _api_copy_key_sessions(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _json_response(_list_copy_key_sessions(config_path))


def _api_copy_key_session(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _read_copy_key_session(config_path, _first_query_value(params, "file", "filename"))


def _api_delete_copy_key_session(
    params: dict[str, list[str]], config_path: Path | None
) -> HttpResponse:
    return _delete_copy_key_session(config_path, _first_query_value(params, "file", "filename"))


def _api_copy_key_band_evidence(
    params: dict[str, list[str]], config_path: Path | None
) -> HttpResponse:
    return _json_response(
        _read_copy_key_band_evidence(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
            window_size_raw=_optional_query_value(params, "window_size"),
        )
    )


def _api_copy_key_band_history(
    params: dict[str, list[str]], config_path: Path | None
) -> HttpResponse:
    return _json_response(
        _read_copy_key_band_history(
            config_path,
            claimed_set_key=_optional_query_value(params, "claimed_set_key"),
        )
    )


def _api_backup(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return _build_records_backup(config_path, kind=_first_query_value(params, "kind"))


def _api_voice_lexicon(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    language = _first_query_value(params, "language") or "en"
    return voice_lexicon_response(language)


def _api_voice_status(params: dict[str, list[str]], config_path: Path | None) -> HttpResponse:
    return voice_status_response(config_path)


_API_ROUTES: dict[str, ApiHandler] = {
    "/api/version": _api_version,
    "/api/koch-exercises": _api_koch_exercises,
    "/api/koch-exercise": _api_koch_exercise,
    "/api/delete-koch-exercise": _api_delete_koch_exercise,
    "/api/koch-band-evidence": _api_koch_band_evidence,
    "/api/koch-band-history": _api_koch_band_history,
    "/api/koch-burden-profile": _api_koch_burden_profile,
    "/api/koch-attention-response": _api_koch_attention_response,
    "/api/koch-confusion": _api_koch_confusion,
    "/api/recognition-confusion": _api_recognition_confusion,
    "/api/recognition-timing": _api_recognition_timing,
    "/api/recognition-burden-profile": _api_recognition_burden_profile,
    "/api/recognition-attention-response": _api_recognition_attention_response,
    "/api/recognitions": _api_recognitions,
    "/api/recognition": _api_recognition,
    "/api/delete-recognition": _api_delete_recognition,
    "/api/cadence-sends": _api_cadence_sends,
    "/api/cadence-send": _api_cadence_send,
    "/api/delete-cadence-send": _api_delete_cadence_send,
    "/api/cadence-band-evidence": _api_cadence_band_evidence,
    "/api/cadence-band-history": _api_cadence_band_history,
    "/api/copy-key-sessions": _api_copy_key_sessions,
    "/api/copy-key-session": _api_copy_key_session,
    "/api/delete-copy-key-session": _api_delete_copy_key_session,
    "/api/copy-key-band-evidence": _api_copy_key_band_evidence,
    "/api/copy-key-band-history": _api_copy_key_band_history,
    "/api/backup": _api_backup,
    "/api/voice/lexicon": _api_voice_lexicon,
    "/api/voice/status": _api_voice_status,
}


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _http_response(
    status: HTTPStatus, body: bytes
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    return (
        status,
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
        body,
    )


def _json_response(payload: dict[str, Any]) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
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


# ---------------------------------------------------------------------------
# Filename validation patterns
# ---------------------------------------------------------------------------

_KOCH_FILENAME_RE = re.compile(r"^[0-9A-Za-z._/-]+\.json$")
_CADENCE_FILENAME_RE = re.compile(r"^cadence-send-[0-9A-Za-z-]+\.json$")
_COPY_KEY_FILENAME_RE = re.compile(r"^copy-key-[0-9A-Za-z-]+\.json$")
_RECOGNITION_FILENAME_RE = re.compile(r"^[0-9A-Za-z._/-]+\.json$")
_RECORD_PATH_PART_RE = re.compile(r"^[0-9A-Za-z._-]+$")


# ---------------------------------------------------------------------------
# Generic record helpers
# ---------------------------------------------------------------------------


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


def _safe_relative_record_path(filename: str) -> Path | None:
    path = PurePosixPath(filename)
    if path.is_absolute() or not path.parts:
        return None
    if any(part in ("", ".", "..") for part in path.parts):
        return None
    if not all(_RECORD_PATH_PART_RE.fullmatch(part) for part in path.parts):
        return None
    return Path(*path.parts)


def _read_record_file(
    *,
    config_path: Path | None,
    filename: str,
    filename_re: re.Pattern[str],
    subdirectory: str,
    mode: str,
    transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    allow_relative_filename: bool = False,
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
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
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
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


def _resolve_records_and_key(
    config_path: Path | None,
    *,
    iter_records: Callable[[Path], list[dict[str, Any]]],
    extract_key: Callable[[dict[str, Any]], str],
    claimed_set_key: str | None,
    transform: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
) -> tuple[Path, list[dict[str, Any]], str]:
    """Load records and resolve the claimed-set key for evidence/history endpoints.

    Resolves save_directory, loads records via ``iter_records``,
    optionally transforms them, and when ``claimed_set_key`` is omitted
    defaults to the most recent record's key via ``extract_key``.

    Raises on save_directory resolution failure — callers catch and
    return their own error fallback dict.
    """
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


def _parse_window_size(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

_BACKUP_KINDS: dict[str, str] = {
    "koch-exercise": "koch-exercise",
    "cadence-send": "cadence-send",
    "copy-key": "copy-key",
    "recognition": "recognition",
}


def _build_records_backup(
    config_path: Path | None,
    *,
    kind: str,
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    subdir = _BACKUP_KINDS.get(kind)
    if subdir is None:
        return _http_response(HTTPStatus.BAD_REQUEST, b"unknown backup kind")

    try:
        save_directory = load_save_directory(config_path)
    except Exception:
        logger.exception("could not resolve save_directory for backup")
        return _http_response(HTTPStatus.INTERNAL_SERVER_ERROR, b"could not resolve save directory")

    target_dir = save_directory / subdir
    pattern = "*.json" if kind in ("koch-exercise", "recognition") else f"{subdir}-*.json"

    buffer = io.BytesIO()
    file_count = 0
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        if target_dir.is_dir():
            for entry in sorted(target_dir.rglob(pattern)):
                try:
                    payload = entry.read_bytes()
                except OSError:
                    logger.exception("skipping unreadable record in backup: %s", entry)
                    continue
                archive.writestr(str(entry.relative_to(save_directory)), payload)
                file_count += 1

    body = buffer.getvalue()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"copy-653-{subdir}-backup-{stamp}.zip"
    return (
        HTTPStatus.OK,
        [
            ("Content-Type", "application/zip"),
            ("Content-Length", str(len(body))),
            ("Content-Disposition", f'attachment; filename="{filename}"'),
            ("X-Copy-Backup-File-Count", str(file_count)),
            ("Cache-Control", "no-store"),
        ],
        body,
    )


# ---------------------------------------------------------------------------
# Koch exercise endpoints
# ---------------------------------------------------------------------------


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


def _list_koch_exercises(config_path: Path | None) -> dict[str, Any]:
    return _list_records(
        config_path,
        subdirectory="koch-exercise",
        mode="koch-exercise",
        enrich=_enrich_koch_record,
        glob_pattern="*.json",
        relative_filenames=True,
    )


def _read_koch_exercise(
    config_path: Path | None, filename: str
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    return _read_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_KOCH_FILENAME_RE,
        subdirectory="koch-exercise",
        mode="koch-exercise",
        allow_relative_filename=True,
    )


def _delete_koch_exercise(
    config_path: Path | None, filename: str
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    return _delete_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_KOCH_FILENAME_RE,
        subdirectory="koch-exercise",
        mode="koch-exercise",
        allow_relative_filename=True,
    )


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
        save_directory, records, resolved_key = _resolve_records_and_key(
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


def _iter_recognition_and_koch_records(save_directory: Path) -> list[dict[str, Any]]:
    """Load records needed for Recognition burden debt and transfer evidence."""
    return [
        *_iter_recognition_records(save_directory),
        *_iter_koch_records(save_directory),
    ]


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


# ---------------------------------------------------------------------------
# Recognition record endpoints (records table / calendar / backup)
# ---------------------------------------------------------------------------


def _enrich_recognition_record(data: dict[str, Any], entry: dict[str, Any]) -> None:
    generation = data.get("generation") or {}
    set_id = generation.get("set_id")
    if isinstance(set_id, str) and set_id:
        entry["set_id"] = set_id
    set_session = generation.get("set_session")
    if isinstance(set_session, int) and not isinstance(set_session, bool):
        entry["set_session"] = set_session


def _list_recognitions(config_path: Path | None) -> dict[str, Any]:
    return _list_records(
        config_path,
        subdirectory="recognition",
        mode="recognition",
        enrich=_enrich_recognition_record,
        glob_pattern="*.json",
        relative_filenames=True,
    )


def _read_recognition(
    config_path: Path | None, filename: str
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    return _read_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_RECOGNITION_FILENAME_RE,
        subdirectory="recognition",
        mode="recognition",
        transform=attach_recognition_review_analysis,
        allow_relative_filename=True,
    )


def _delete_recognition(
    config_path: Path | None, filename: str
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    return _delete_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_RECOGNITION_FILENAME_RE,
        subdirectory="recognition",
        mode="recognition",
        allow_relative_filename=True,
    )


# ---------------------------------------------------------------------------
# Cadence send endpoints
# ---------------------------------------------------------------------------


def _list_cadence_sends(config_path: Path | None) -> dict[str, Any]:
    return _list_records(config_path, subdirectory="cadence-send", mode="cadence-send")


def _read_cadence_send(
    config_path: Path | None, filename: str
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    return _read_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_CADENCE_FILENAME_RE,
        subdirectory="cadence-send",
        mode="cadence-send",
    )


def _delete_cadence_send(
    config_path: Path | None, filename: str
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    return _delete_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_CADENCE_FILENAME_RE,
        subdirectory="cadence-send",
        mode="cadence-send",
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


# ---------------------------------------------------------------------------
# Copy Key endpoints
# ---------------------------------------------------------------------------


def _list_copy_key_sessions(config_path: Path | None) -> dict[str, Any]:
    return _list_records(config_path, subdirectory="copy-key", mode="copy-key")


def _read_copy_key_session(
    config_path: Path | None, filename: str
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    return _read_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_COPY_KEY_FILENAME_RE,
        subdirectory="copy-key",
        mode="copy-key",
        transform=backfill_copy_key_record,
    )


def _delete_copy_key_session(
    config_path: Path | None, filename: str
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    return _delete_record_file(
        config_path=config_path,
        filename=filename,
        filename_re=_COPY_KEY_FILENAME_RE,
        subdirectory="copy-key",
        mode="copy-key",
    )


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
