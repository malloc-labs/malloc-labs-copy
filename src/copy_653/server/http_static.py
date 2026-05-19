"""Static HTTP surface served alongside the WebSocket endpoint.

Spec §1.4: the engine and UI live on one TCP port; non-WS requests
are answered as plain HTTP from the ``web/`` directory. Everything
in this module is pure — no engine state crosses the seam.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from websockets.datastructures import Headers

from copy_653 import __version__
from copy_653.config import load_save_directory
from copy_653.sequence.exercise_analysis import (
    DEFAULT_EVIDENCE_WINDOW_SIZE,
    load_band_evidence,
    load_band_history,
    record_claimed_set_key,
)
from copy_653.sequence.cadence_analysis import (
    DEFAULT_EVIDENCE_WINDOW_SIZE as CADENCE_EVIDENCE_WINDOW_SIZE,
    load_band_evidence as load_cadence_band_evidence,
    load_band_history as load_cadence_band_history,
    record_claimed_set_key as cadence_record_claimed_set_key,
)
from copy_653.server.records import _iter_cadence_records, _iter_koch_records

logger = logging.getLogger(__name__)


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
        # Strip the query string for static lookups; we do not use it
        # for anything in v0.
        parsed_path = urlsplit(path)
        clean_path = parsed_path.path

        # /ws is the only WS endpoint. Returning None hands control
        # back to websockets to complete the upgrade.
        if clean_path == "/ws":
            return None

        if clean_path == "/api/version":
            return _json_response({"version": __version__})

        if clean_path == "/api/koch-exercises":
            return _json_response(_list_koch_exercises(config_path))

        if clean_path == "/api/koch-exercise":
            params = parse_qs(parsed_path.query)
            filename_values = params.get("file") or params.get("filename") or []
            filename = filename_values[0] if filename_values else ""
            return _read_koch_exercise(config_path, filename)

        if clean_path == "/api/koch-band-evidence":
            params = parse_qs(parsed_path.query)
            key_values = params.get("claimed_set_key") or []
            window_values = params.get("window_size") or []
            return _json_response(
                _read_koch_band_evidence(
                    config_path,
                    claimed_set_key=key_values[0] if key_values else None,
                    window_size_raw=window_values[0] if window_values else None,
                )
            )

        if clean_path == "/api/koch-band-history":
            params = parse_qs(parsed_path.query)
            key_values = params.get("claimed_set_key") or []
            return _json_response(
                _read_koch_band_history(
                    config_path,
                    claimed_set_key=key_values[0] if key_values else None,
                )
            )

        if clean_path == "/api/cadence-sends":
            return _json_response(_list_cadence_sends(config_path))

        if clean_path == "/api/cadence-send":
            params = parse_qs(parsed_path.query)
            filename_values = params.get("file") or params.get("filename") or []
            filename = filename_values[0] if filename_values else ""
            return _read_cadence_send(config_path, filename)

        if clean_path == "/api/cadence-band-evidence":
            params = parse_qs(parsed_path.query)
            key_values = params.get("claimed_set_key") or []
            window_values = params.get("window_size") or []
            return _json_response(
                _read_cadence_band_evidence(
                    config_path,
                    claimed_set_key=key_values[0] if key_values else None,
                    window_size_raw=window_values[0] if window_values else None,
                )
            )

        if clean_path == "/api/cadence-band-history":
            params = parse_qs(parsed_path.query)
            key_values = params.get("claimed_set_key") or []
            return _json_response(
                _read_cadence_band_history(
                    config_path,
                    claimed_set_key=key_values[0] if key_values else None,
                )
            )

        target = "index.html" if clean_path == "/" else clean_path.lstrip("/")
        resolved = (web_root / target).resolve()

        # Defence in depth against path traversal — a request like
        # /../etc/passwd should 404, not escape the web root.
        try:
            resolved.relative_to(web_root)
        except ValueError:
            return _http_response(HTTPStatus.NOT_FOUND, b"not found")

        if not resolved.is_file():
            return _http_response(HTTPStatus.NOT_FOUND, b"not found")

        body = resolved.read_bytes()
        mime, _ = mimetypes.guess_type(resolved.name)
        content_type = mime or "application/octet-stream"
        # Modern browsers want charset=utf-8 on text payloads — without
        # it Firefox in particular complains about the meta charset.
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


def _list_koch_exercises(config_path: Path | None) -> dict[str, Any]:
    """List saved koch-exercise records for the settings UI.

    Reads the save directory fresh from disk (spec §6.3), enumerates
    ``<save_dir>/koch-exercise/koch-exercise-*.json``, and returns each
    record's started_at timestamp and claimed set. Files that fail to
    parse are skipped — a corrupt or non-koch record should not 500 the
    settings page. Order is newest first.
    """
    try:
        save_directory = load_save_directory(config_path)
    except Exception:
        logger.exception("could not resolve save_directory for koch-exercise listing")
        return {"save_directory": "", "records": []}

    target_dir = save_directory / "koch-exercise"
    records: list[dict[str, Any]] = []
    if target_dir.is_dir():
        for entry in sorted(target_dir.glob("koch-exercise-*.json")):
            try:
                data = json.loads(entry.read_text())
            except (OSError, ValueError):
                logger.exception("skipping unreadable koch-exercise record: %s", entry)
                continue
            if data.get("mode") != "koch-exercise":
                continue
            started_at = data.get("started_at")
            claimed_set = data.get("claimed_set")
            if not isinstance(started_at, str) or not isinstance(claimed_set, list):
                continue
            exercises = data.get("exercises")
            exercise_count = len(exercises) if isinstance(exercises, list) else 0
            records.append(
                {
                    "filename": entry.name,
                    "started_at": started_at,
                    "claimed_set": [str(s) for s in claimed_set],
                    "exercise_count": exercise_count,
                }
            )

    records.sort(key=lambda r: r["started_at"], reverse=True)
    return {"save_directory": str(save_directory), "records": records}


# Files written by the engine match koch-exercise-<UTC-stamp>.json (with
# optional -N collision suffix); this rejects path separators and anything
# else that could escape the koch-exercise subdirectory.
_KOCH_FILENAME_RE = re.compile(r"^koch-exercise-[0-9A-Za-z-]+\.json$")
_CADENCE_FILENAME_RE = re.compile(r"^cadence-send-[0-9A-Za-z-]+\.json$")


def _read_koch_band_evidence(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
    window_size_raw: str | None,
) -> dict[str, Any]:
    """Return per-band evidence for the Settings rollup view.

    When ``claimed_set_key`` is omitted the most recent saved record's
    key is used — that is almost always the one the learner wants to
    see, and it avoids the page needing a second round-trip to discover
    which key is current. Records that fail to parse are skipped.
    """
    try:
        save_directory = load_save_directory(config_path)
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

    records = _iter_koch_records(save_directory)
    resolved_key = claimed_set_key
    if not resolved_key:
        latest = max(
            records,
            key=lambda r: str(r.get("started_at") or ""),
            default=None,
        )
        resolved_key = record_claimed_set_key(latest) if latest else ""

    window_size = DEFAULT_EVIDENCE_WINDOW_SIZE
    if window_size_raw is not None:
        try:
            parsed = int(window_size_raw)
        except (TypeError, ValueError):
            parsed = window_size
        if parsed > 0:
            window_size = parsed

    evidence = load_band_evidence(
        records,
        claimed_set_key=resolved_key,
        window_size=window_size,
    )
    evidence["save_directory"] = str(save_directory)
    return evidence


def _read_koch_band_history(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
) -> dict[str, Any]:
    """Return per-band lifetime history for the Settings full-history modal.

    Mirrors :func:`_read_koch_band_evidence` for the rollup endpoint —
    when ``claimed_set_key`` is omitted, the most-recent saved
    record's key is used so the page does not need a separate
    round-trip to discover which key is current.
    """
    try:
        save_directory = load_save_directory(config_path)
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

    records = _iter_koch_records(save_directory)
    resolved_key = claimed_set_key
    if not resolved_key:
        latest = max(
            records,
            key=lambda r: str(r.get("started_at") or ""),
            default=None,
        )
        resolved_key = record_claimed_set_key(latest) if latest else ""

    history = load_band_history(records, claimed_set_key=resolved_key)
    history["save_directory"] = str(save_directory)
    return history


def _read_koch_exercise(
    config_path: Path | None, filename: str
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    """Return the full JSON record for one koch-exercise file.

    Validates ``filename`` strictly against the engine's write pattern
    before resolving — a request for ``../foo.json`` or any path with a
    separator is refused without touching the filesystem. The file is
    resolved under ``<save_directory>/koch-exercise/`` and a final
    ``relative_to`` check guards against symlink shenanigans.
    """
    if not filename or not _KOCH_FILENAME_RE.fullmatch(filename):
        return _http_response(HTTPStatus.BAD_REQUEST, b"invalid filename")

    try:
        save_directory = load_save_directory(config_path)
    except Exception:
        logger.exception("could not resolve save_directory for koch-exercise read")
        return _http_response(HTTPStatus.INTERNAL_SERVER_ERROR, b"save directory unavailable")

    target_dir = (save_directory / "koch-exercise").resolve()
    resolved = (target_dir / filename).resolve()
    try:
        resolved.relative_to(target_dir)
    except ValueError:
        return _http_response(HTTPStatus.NOT_FOUND, b"not found")
    if not resolved.is_file():
        return _http_response(HTTPStatus.NOT_FOUND, b"not found")

    try:
        data = json.loads(resolved.read_text())
    except (OSError, ValueError):
        logger.exception("failed to read koch-exercise record: %s", resolved)
        return _http_response(HTTPStatus.INTERNAL_SERVER_ERROR, b"read failed")
    if not isinstance(data, dict) or data.get("mode") != "koch-exercise":
        return _http_response(HTTPStatus.NOT_FOUND, b"not found")

    return _json_response(data)


def _list_cadence_sends(config_path: Path | None) -> dict[str, Any]:
    """List saved cadence-send records for the settings UI."""
    try:
        save_directory = load_save_directory(config_path)
    except Exception:
        logger.exception("could not resolve save_directory for cadence-send listing")
        return {"save_directory": "", "records": []}

    target_dir = save_directory / "cadence-send"
    records: list[dict[str, Any]] = []
    if target_dir.is_dir():
        for entry in sorted(target_dir.glob("cadence-send-*.json")):
            try:
                data = json.loads(entry.read_text())
            except (OSError, ValueError):
                logger.exception("skipping unreadable cadence-send record: %s", entry)
                continue
            if data.get("mode") != "cadence-send":
                continue
            started_at = data.get("started_at")
            claimed_set = data.get("claimed_set")
            exercises = data.get("exercises")
            if (
                not isinstance(started_at, str)
                or not isinstance(claimed_set, list)
                or not isinstance(exercises, list)
            ):
                continue
            records.append(
                {
                    "filename": entry.name,
                    "started_at": started_at,
                    "claimed_set": [str(s) for s in claimed_set],
                    "exercise_count": len(exercises),
                }
            )

    records.sort(key=lambda r: r["started_at"], reverse=True)
    return {"save_directory": str(save_directory), "records": records}


def _read_cadence_band_evidence(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
    window_size_raw: str | None,
) -> dict[str, Any]:
    try:
        save_directory = load_save_directory(config_path)
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

    records = _iter_cadence_records(save_directory)
    resolved_key = claimed_set_key
    if not resolved_key:
        latest = max(records, key=lambda r: str(r.get("started_at") or ""), default=None)
        resolved_key = cadence_record_claimed_set_key(latest) if latest else ""

    window_size = CADENCE_EVIDENCE_WINDOW_SIZE
    if window_size_raw is not None:
        try:
            parsed = int(window_size_raw)
        except (TypeError, ValueError):
            parsed = window_size
        if parsed > 0:
            window_size = parsed

    evidence = load_cadence_band_evidence(
        records,
        claimed_set_key=resolved_key,
        window_size=window_size,
    )
    evidence["save_directory"] = str(save_directory)
    return evidence


def _read_cadence_band_history(
    config_path: Path | None,
    *,
    claimed_set_key: str | None,
) -> dict[str, Any]:
    """Return per-band lifetime history for the Key full-history modal.

    Mirrors :func:`_read_koch_band_history` — when ``claimed_set_key``
    is omitted, the most-recent saved cadence record's key is used so
    the page does not need a separate round-trip to discover the
    current key.
    """
    try:
        save_directory = load_save_directory(config_path)
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

    records = _iter_cadence_records(save_directory)
    resolved_key = claimed_set_key
    if not resolved_key:
        latest = max(
            records,
            key=lambda r: str(r.get("started_at") or ""),
            default=None,
        )
        resolved_key = cadence_record_claimed_set_key(latest) if latest else ""

    history = load_cadence_band_history(records, claimed_set_key=resolved_key)
    history["save_directory"] = str(save_directory)
    return history


def _read_cadence_send(
    config_path: Path | None, filename: str
) -> tuple[HTTPStatus, list[tuple[str, str]], bytes]:
    if not filename or not _CADENCE_FILENAME_RE.fullmatch(filename):
        return _http_response(HTTPStatus.BAD_REQUEST, b"invalid filename")

    try:
        save_directory = load_save_directory(config_path)
    except Exception:
        logger.exception("could not resolve save_directory for cadence-send read")
        return _http_response(HTTPStatus.INTERNAL_SERVER_ERROR, b"save directory unavailable")

    target_dir = (save_directory / "cadence-send").resolve()
    resolved = (target_dir / filename).resolve()
    try:
        resolved.relative_to(target_dir)
    except ValueError:
        return _http_response(HTTPStatus.NOT_FOUND, b"not found")
    if not resolved.is_file():
        return _http_response(HTTPStatus.NOT_FOUND, b"not found")

    try:
        data = json.loads(resolved.read_text())
    except (OSError, ValueError):
        logger.exception("failed to read cadence-send record: %s", resolved)
        return _http_response(HTTPStatus.INTERNAL_SERVER_ERROR, b"read failed")
    if not isinstance(data, dict) or data.get("mode") != "cadence-send":
        return _http_response(HTTPStatus.NOT_FOUND, b"not found")

    return _json_response(data)
