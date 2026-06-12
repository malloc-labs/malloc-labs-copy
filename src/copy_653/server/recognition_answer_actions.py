"""Recognition answer WebSocket actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from websockets.server import WebSocketServerProtocol

from copy_653.server.records import _save_recognition_answers
from copy_653.server.wire_events import _send_event


async def _save_recognition_answers_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
    pending_path: Path | None,
) -> bool:
    """Merge learner answers — and optional per-exercise voice capture —
    into the most recently written recognition record.

    Mirrors :func:`_save_koch_answers_action`. ``answers`` is parallel
    to the record's ``exercises``; length mismatch is rejected per
    spec §1.5 rather than silently padded.

    The optional ``voice_capture`` field is a list of lists parallel to
    ``answers``: each inner list holds the Vosk events that produced
    that exercise's answer, as ``{t, text, symbols}`` dicts (see phase
    5.1). Shape is enforced strictly — invalid shapes are rejected
    rather than silently dropped.
    """
    if pending_path is None:
        await _send_event(ws, {"type": "error", "reason": "no-pending-recognition-record"})
        return False

    raw_answers = message.get("answers")
    if not isinstance(raw_answers, list) or not all(isinstance(a, str) for a in raw_answers):
        await _send_event(ws, {"type": "error", "reason": "invalid-answers"})
        return False

    raw_voice = message.get("voice_capture")
    voice_capture: list[list[dict[str, Any]]] | None
    if raw_voice is None:
        voice_capture = None
    else:
        voice_capture = _coerce_voice_capture(raw_voice)
        if voice_capture is None:
            await _send_event(ws, {"type": "error", "reason": "invalid-voice-capture"})
            return False

    try:
        exercise_count = _save_recognition_answers(
            pending_path,
            list(raw_answers),
            voice_capture=voice_capture,
        )
    except ValueError as exc:
        await _send_event(
            ws,
            {"type": "error", "reason": "answers-length-mismatch", "detail": str(exc)},
        )
        return False
    except FileNotFoundError:
        await _send_event(ws, {"type": "error", "reason": "pending-recognition-record-missing"})
        return False

    await _send_event(
        ws,
        {
            "type": "recognition-answers-saved",
            "answer_count": len(raw_answers),
            "exercise_count": exercise_count,
        },
    )
    return True


def _coerce_voice_capture(raw: Any) -> list[list[dict[str, Any]]] | None:
    """Return a sanitised voice_capture or ``None`` if the shape is wrong.

    Each entry must be a list (parallel to exercises) of dicts with
    ``text: str`` and ``symbols: list[str]``. Optional timing fields are
    preserved when present. Unknown keys are dropped silently for
    forward compatibility.
    """
    if not isinstance(raw, list):
        return None
    out: list[list[dict[str, Any]]] = []
    for per_exercise in raw:
        if not isinstance(per_exercise, list):
            return None
        sanitised: list[dict[str, Any]] = []
        for entry in per_exercise:
            if not isinstance(entry, dict):
                return None
            text = entry.get("text")
            symbols = entry.get("symbols")
            if not isinstance(text, str):
                return None
            if not isinstance(symbols, list) or not all(isinstance(s, str) for s in symbols):
                return None
            clean: dict[str, Any] = {"text": text, "symbols": list(symbols)}
            t = entry.get("t")
            if isinstance(t, (int, float)) and not isinstance(t, bool):
                clean["t"] = float(t)
            for key in ("first_partial_t", "last_partial_t"):
                value = entry.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    clean[key] = float(value)
            symbol_events = entry.get("symbol_events")
            if isinstance(symbol_events, list):
                clean_events: list[dict[str, Any]] = []
                for event in symbol_events:
                    if not isinstance(event, dict):
                        continue
                    symbol = event.get("symbol")
                    event_t = event.get("t")
                    if not isinstance(symbol, str):
                        continue
                    if not isinstance(event_t, (int, float)) or isinstance(event_t, bool):
                        continue
                    clean_event: dict[str, Any] = {"symbol": symbol, "t": float(event_t)}
                    index = event.get("index")
                    if isinstance(index, int) and not isinstance(index, bool):
                        clean_event["index"] = index
                    source = event.get("source")
                    if isinstance(source, str):
                        clean_event["source"] = source
                    clean_events.append(clean_event)
                if clean_events:
                    clean["symbol_events"] = clean_events
            sanitised.append(clean)
        out.append(sanitised)
    return out
