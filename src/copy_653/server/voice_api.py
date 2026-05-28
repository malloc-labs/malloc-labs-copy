"""HTTP API handlers for the Voice settings tab.

Two read-only endpoints back the settings UI without forcing the
caller to open a WS or load the heavy ``vosk`` dependency:

* ``GET /api/voice/lexicon`` — merged symbol → phrases mapping plus
  the raw bundled JSON files, so the settings page can show both a
  flat reference table and the per-category source-of-truth files.
* ``GET /api/voice/status`` — readiness summary: configured language
  and ``model_path``, the absolute path that would be loaded, and
  whether the directory currently exists. Lets the UI tell the
  learner "voice is configured but the model directory is missing"
  without opening a recogniser.

Per spec §1.5 honesty contract, these endpoints surface their
underlying state directly. They do NOT validate the lexicon or model
beyond what is observable through the filesystem and the existing
:func:`load_lexicon` / :class:`VoiceSettings` loaders.
"""

from __future__ import annotations

import importlib
import json
from http import HTTPStatus
from pathlib import Path
from typing import Any

from copy_653.config import load_voice_settings
from copy_653.voice.lexicon import DEFAULT_LEXICON_DIR, LexiconError, load_lexicon

HttpResponse = tuple[HTTPStatus, list[tuple[str, str]], bytes]


def voice_lexicon_response(language: str = "en") -> HttpResponse:
    """Build the ``GET /api/voice/lexicon`` response body."""
    files: list[dict[str, Any]] = []
    for path in sorted(DEFAULT_LEXICON_DIR.glob(f"*_{language}.json")):
        files.append({"name": path.name, "json": json.loads(path.read_text(encoding="utf-8"))})

    payload: dict[str, Any] = {"language": language, "files": files}

    try:
        lex = load_lexicon(language)
    except LexiconError as err:
        # Surface load failures verbatim — the settings page is the
        # right place to see them.
        payload["merged"] = None
        payload["error"] = str(err)
    else:
        payload["merged"] = {symbol: list(phrases) for symbol, phrases in lex.entries.items()}
        payload["error"] = None

    return _json_response(payload)


def voice_status_response(config_path: Path | None) -> HttpResponse:
    """Build the ``GET /api/voice/status`` response body."""
    settings = load_voice_settings(config_path)
    resolved = settings.resolved_model_path()
    model_exists = bool(resolved and Path(resolved).is_dir())
    vosk_installed = _is_vosk_installed()

    payload = {
        "language": settings.language,
        "model_path": settings.model_path,
        "model_path_resolved": str(resolved) if resolved is not None else None,
        "model_exists": model_exists,
        "vosk_installed": vosk_installed,
        "ready": (settings.model_path is not None) and model_exists and vosk_installed,
    }
    return _json_response(payload)


def _is_vosk_installed() -> bool:
    try:
        importlib.import_module("vosk")
    except ImportError:
        return False
    return True


def _json_response(payload: dict[str, Any]) -> HttpResponse:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return (
        HTTPStatus.OK,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
        ],
        body,
    )
