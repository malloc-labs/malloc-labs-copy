"""Cadence and Copy Key WebSocket actions."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from websockets.server import WebSocketServerProtocol

from copy_653 import sequence
from copy_653.audio import playback, synth, texture
from copy_653.config import load_audio_parameters, load_claimed_symbols, load_save_directory
from copy_653.server.records import (
    _ActiveCadenceSession,
    _ActiveCopyKeySession,
    _next_cadence_run_index,
    _next_copy_key_run_index,
    _resolve_cadence_session_gears,
    _resolve_copy_key_session_gears,
)
from copy_653.server.validation import _optional_positive_int
from copy_653.server.wire_events import _send_event
from copy_653.sequence.cadence_analysis import (
    build_cadence_exercise_entries,
    build_cadence_generation_profile,
)
from copy_653.sequence.copy_exercises import DEFAULT_EXERCISE_COUNT, DEFAULT_MAX_IDENTICAL_RUN
from copy_653.sequence.copy_key_exercises import (
    DEFAULT_EXERCISE_COUNT as COPY_KEY_DEFAULT_EXERCISE_COUNT,
)


async def _request_copy_exercises_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
    config_path: Path,
) -> _ActiveCadenceSession | None:
    """Generate short copy exercises from the claimed set and push them.

    Used by the Cadence page's Copy section. Display-only on the
    client today; the engine owns generation so the seed is recorded
    and the lexicon swap stays a single-module change.

    Returns a freshly-opened :class:`_ActiveCadenceSession` on success
    (the handler will hold it for the duration of the keying), or
    ``None`` if the request was rejected (invalid args, empty claimed
    set, generator failure).
    """
    try:
        overrides = {
            "exercise_count": _optional_positive_int(
                message.get("exercise_count"), "exercise_count"
            ),
            "min_words": _optional_positive_int(message.get("min_words"), "min_words"),
            "max_words": _optional_positive_int(message.get("max_words"), "max_words"),
            "min_word_length": _optional_positive_int(
                message.get("min_word_length"), "min_word_length"
            ),
            "max_word_length": _optional_positive_int(
                message.get("max_word_length"), "max_word_length"
            ),
        }
    except ValueError as exc:
        await _send_event(
            ws,
            {"type": "error", "reason": "invalid-copy-exercises-request", "detail": str(exc)},
        )
        return None

    claimed = load_claimed_symbols(config_path)
    if not claimed:
        await _send_event(ws, {"type": "error", "reason": "no-claimed-symbols"})
        return None

    exercise_count = overrides["exercise_count"] or DEFAULT_EXERCISE_COUNT
    save_directory = load_save_directory(config_path)
    claimed_set_key = " ".join(sorted(claimed))
    gears = _resolve_cadence_session_gears(
        save_directory, claimed_set_key, exercise_count=exercise_count
    )

    kwargs: dict[str, Any] = {"claimed_set": claimed}
    for name, value in overrides.items():
        if value is not None:
            kwargs[name] = value
    kwargs["gears"] = gears
    kwargs["max_identical_run"] = DEFAULT_MAX_IDENTICAL_RUN

    try:
        result = sequence.generate_copy_exercises(**kwargs)
    except ValueError as exc:
        await _send_event(
            ws,
            {"type": "error", "reason": "invalid-copy-exercises-request", "detail": str(exc)},
        )
        return None

    await _send_event(
        ws,
        {
            "type": "copy-exercises",
            "exercises": list(result.exercises),
            "seed": result.seed,
            "claimed_set": list(result.claimed_set),
        },
    )

    # Capture request params as the learner asked for them (after
    # validation, before defaulting) so the record reflects intent
    # rather than the engine's fallbacks.
    request_payload = {k: v for k, v in overrides.items() if v is not None}
    generation = build_cadence_generation_profile(
        claimed_set=claimed,
        candidate_count=result.candidate_count,
        exercise_count=len(result.exercises),
        gears=gears,
    )
    generation["run_index"] = _next_cadence_run_index(save_directory, claimed_set_key)
    return _ActiveCadenceSession(
        started_at=datetime.now(timezone.utc),
        audio=load_audio_parameters(config_path),
        claimed=claimed,
        request=request_payload,
        seed=result.seed,
        generation=generation,
        exercises=build_cadence_exercise_entries(
            list(result.exercises),
            scores=result.scores,
            gears=gears,
        ),
    )


async def _request_copy_key_exercises_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
) -> _ActiveCopyKeySession | None:
    """Generate Copy Key exercises and open a session.

    Generates short head-copy exercises (single words, 1-4 symbols,
    max 2 words / 5 total symbols, gear 0 capped at 4), synthesises
    the audio for each,
    and sends the exercise list to the client. Returns an active
    session holding the pre-rendered per-exercise audio buffers so
    ``play-copy-key-exercise`` can play them on demand.
    """
    audio_params = load_audio_parameters(config_path)
    claimed = load_claimed_symbols(config_path)

    if not claimed:
        await _send_event(ws, {"type": "error", "reason": "no-claimed-symbols"})
        return None

    exercise_count = COPY_KEY_DEFAULT_EXERCISE_COUNT
    save_directory = load_save_directory(config_path)
    claimed_set_key = " ".join(sorted(claimed))
    gears = _resolve_copy_key_session_gears(
        save_directory, claimed_set_key, exercise_count=exercise_count
    )

    try:
        result = sequence.generate_copy_key_exercises(
            claimed_set=claimed,
            gears=gears,
        )
    except ValueError as exc:
        await _send_event(
            ws,
            {"type": "error", "reason": "invalid-copy-key-request", "detail": str(exc)},
        )
        return None

    exercises = list(result.exercises)
    exercise_entries: list[dict[str, Any]] = []
    for idx, target in enumerate(exercises):
        exercise_entries.append(
            {
                "index": idx + 1,
                "target": target,
                "burden_score": result.scores[idx] if idx < len(result.scores) else 0,
                "burden_band": idx + 1,
                "gear": gears[idx] if idx < len(gears) else 0,
            }
        )

    generation: dict[str, Any] = {
        "profile_version": "copy-key-burden-v1",
        "claimed_set_key": claimed_set_key,
        "candidate_count": result.candidate_count,
        "bands": [
            {"index": idx + 1, "gear": gears[idx] if idx < len(gears) else 0}
            for idx in range(len(exercises))
        ],
        "run_index": _next_copy_key_run_index(save_directory, claimed_set_key),
    }

    # Build per-exercise audio and timelines. Each exercise is short
    # (1-5 symbols) so we render them individually rather than as a
    # single concatenated buffer — the learner hears one, keys it back,
    # then hears the next.
    per_exercise_audio: list[tuple[Any, list[Any]]] = []
    for exercise_index, exercise in enumerate(exercises, start=1):
        words = exercise.split(" ")
        exercise_audio = synth.synthesize_words(words, audio_params)
        exercise_audio = texture.add_receiver_bed(
            exercise_audio,
            audio_params,
            context=f"copy-key:{exercise_index}:{exercise}",
        )
        exercise_timeline = synth.compute_word_timeline(words, audio_params)
        symbols_for_exercise: list[dict[str, Any]] = []
        for symbol, t_on, t_off, word_index, word in exercise_timeline:
            entry = {
                "symbol": symbol,
                "t_on": t_on,
                "t_off": t_off,
                "exercise_index": exercise_index,
                "word_index": word_index,
                "word": word,
            }
            symbols_for_exercise.append(entry)
        per_exercise_audio.append((exercise_audio, symbols_for_exercise))

    await _send_event(
        ws,
        {
            "type": "copy-key-exercises",
            "exercises": exercises,
            "exercise_count": len(exercises),
            "seed": result.seed,
            "claimed_set": list(result.claimed_set),
        },
    )

    session = _ActiveCopyKeySession(
        started_at=datetime.now(timezone.utc),
        audio=audio_params,
        claimed=claimed,
        seed=result.seed,
        generation=generation,
        exercises=exercise_entries,
        symbols=[],
    )
    session._per_exercise_audio = per_exercise_audio
    return session


async def _play_copy_key_exercise(
    ws: WebSocketServerProtocol,
    session: _ActiveCopyKeySession,
    exercise_index: int,
) -> None:
    """Play one pre-rendered Copy Key exercise and emit symbol events.

    Called once per exercise as the learner advances with BK. The same
    function can be called again with the same ``exercise_index`` to
    replay — the client will use this for IMI (repeat) support.
    """
    audio_data = session._per_exercise_audio
    if not audio_data or exercise_index < 1 or exercise_index > len(audio_data):
        await _send_event(
            ws,
            {"type": "error", "reason": "invalid-copy-key-exercise-index"},
        )
        return

    samples, timeline = audio_data[exercise_index - 1]
    audio_params = session.audio

    await _send_event(
        ws,
        {"type": "copy-key-exercise-start", "exercise_index": exercise_index},
    )

    audio_task = asyncio.create_task(asyncio.to_thread(playback.play, samples, audio_params))

    try:
        cursor = 0.0
        for entry in timeline:
            wait = entry["t_on"] - cursor
            if wait > 0:
                await asyncio.sleep(wait)
            cursor = entry["t_on"]
            session.symbols.append(entry)
            await _send_event(ws, {"type": "symbol", **entry})

        await audio_task
        await _send_event(
            ws,
            {"type": "copy-key-exercise-end", "exercise_index": exercise_index},
        )
    except asyncio.CancelledError:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        audio_task.cancel()
        raise
