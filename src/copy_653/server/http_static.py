"""Static HTTP surface served alongside the WebSocket endpoint.

Spec §1.4: the engine and UI live on one TCP port; non-WS requests
are answered as plain HTTP from the ``web/`` directory. Everything
in this module is pure — no engine state crosses the seam.
"""

from __future__ import annotations

import json
import logging
import mimetypes
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from websockets.datastructures import Headers

from copy_653 import __version__
from copy_653.config import load_save_directory
from copy_653.server.backup_api import build_records_backup
from copy_653.server.record_api import (
    _delete_cadence_send,
    _delete_copy_key_session,
    _delete_koch_exercise,
    _delete_recognition,
    _list_cadence_sends,
    _list_copy_key_sessions,
    _list_koch_exercises,
    _list_recognitions,
    _read_cadence_send,
    _read_copy_key_session,
    _read_koch_exercise,
    _read_recognition,
)
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
from copy_653.session.compat import backfill_copy_key_records

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
    return build_records_backup(config_path, kind=_first_query_value(params, "kind"))


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
