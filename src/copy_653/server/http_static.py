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
from typing import Any
from urllib.parse import urlsplit

from websockets.datastructures import Headers

from copy_653 import __version__

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


def _build_static_handler(web_root: Path):
    """Return a ``process_request`` callable bound to ``web_root``.

    The callable is what websockets invokes for every incoming HTTP
    request before deciding whether to upgrade to WS. Returning
    ``None`` lets the WS handshake proceed; returning a 3-tuple
    answers the request as plain HTTP.
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
