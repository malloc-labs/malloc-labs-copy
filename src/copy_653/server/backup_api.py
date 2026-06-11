"""HTTP API helpers for exporting saved records as backup archives."""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path

from copy_653.config import load_save_directory

logger = logging.getLogger(__name__)

HttpResponse = tuple[HTTPStatus, list[tuple[str, str]], bytes]

_BACKUP_KINDS: dict[str, str] = {
    "koch-exercise": "koch-exercise",
    "cadence-send": "cadence-send",
    "copy-key": "copy-key",
    "recognition": "recognition",
}


def build_records_backup(
    config_path: Path | None,
    *,
    kind: str,
) -> HttpResponse:
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


def _http_response(status: HTTPStatus, body: bytes) -> HttpResponse:
    return (
        status,
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
        body,
    )
