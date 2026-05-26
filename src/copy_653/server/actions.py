"""WS action coroutines.

One function per inbound action — each builds events via
:mod:`copy_653.server.wire_events` and parses incoming arguments via
:mod:`copy_653.server.validation`. The dispatch loop in
:mod:`copy_653.server.app` is the only caller.

These functions are intentionally flat: no per-connection state lives
here. State that spans actions (current task slots, active Cadence
session, browser-key-input state) belongs to the dispatch handler.
"""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from websockets.server import WebSocketServerProtocol

from copy_653 import sequence
from copy_653.audio import patterns, playback, synth, texture
from copy_653.audio.parameters import AudioParameters
from copy_653.config import (
    load_audio_parameters,
    load_claimed_symbols,
    load_save_directory,
    save_claimed_symbols,
)
from copy_653.server.exercises_audio import build_exercises_audio
from copy_653.server.records import (
    _ActiveCadenceSession,
    _ActiveCopyKeySession,
    _iter_koch_records,
    _koch_readiness_state,
    _next_cadence_run_index,
    _next_copy_key_run_index,
    _next_send_symbol_readiness,
    _resolve_cadence_session_gears,
    _resolve_copy_key_session_gears,
    _resolve_session_gears_and_rst,
    _save_koch_answers,
    _write_koch_record,
)
from copy_653.server.validation import (
    _optional_positive_int,
)
from copy_653.server.wire_events import (
    _claimed_symbols_event,
    _send_event,
)
from copy_653.sequence.cadence_analysis import (
    build_cadence_exercise_entries,
    build_cadence_generation_profile,
)
from copy_653.sequence.copy_exercises import DEFAULT_EXERCISE_COUNT, DEFAULT_MAX_IDENTICAL_RUN
from copy_653.sequence.copy_key_exercises import (
    DEFAULT_EXERCISE_COUNT as COPY_KEY_DEFAULT_EXERCISE_COUNT,
)
from copy_653.sequence.exercise_analysis import (
    MAX_GEAR,
    build_exercise_entries,
    build_generation_profile,
    load_confusion_pairs,
)

logger = logging.getLogger(__name__)


def _build_warmup_exercises(
    claimed: tuple[str, ...],
    confusion_subs: list[dict[str, Any]],
    exercise_count: int = 5,
) -> tuple[list[str], int]:
    """Build warm-up exercise strings biased toward confusion pairs.

    Each exercise is a single 2-character word (a symbol pair) preceded
    by the DE listening anchor. When confusion data exists, exercises
    prefer pairs drawn from the learner's most-confused symbols; the
    remaining slots are filled with random pairs from the claimed set.

    Returns ``(exercises, seed)`` where exercises already include the
    DE anchor.
    """
    seed = secrets.randbits(64)
    rng = random.Random(seed)
    claimed_list = list(claimed)

    confusion_pairs: list[str] = []
    claimed_set = set(claimed)
    for sub in confusion_subs:
        target = sub.get("target", "")
        typed = sub.get("typed", "")
        if target in claimed_set and typed in claimed_set and target != typed:
            confusion_pairs.append(target + typed)
            confusion_pairs.append(typed + target)

    exercises: list[str] = []
    for _ in range(exercise_count):
        if confusion_pairs and rng.random() < 0.6:
            pair = rng.choice(confusion_pairs)
        else:
            pair = rng.choice(claimed_list) + rng.choice(claimed_list)
        exercises.append(f"DE {pair}")

    return exercises, seed


async def _run_koch_session(
    ws: WebSocketServerProtocol,
    config_path: Path,
    *,
    audio_params: AudioParameters,
    claimed: tuple[str, ...],
    exercises: list[str],
    exercise_entries: list[dict[str, Any]],
    generation: dict[str, Any],
    samples: Any,
    timeline: list[Any],
    seed: int,
    set_session: int,
    warm_up: bool = False,
) -> Path | None:
    """Play exercises, emit timeline events, write the session record.

    Shared lifecycle for both warm-up and main Koch sessions. The caller
    prepares exercises, generation profile, and audio; this function
    owns the play-emit-record-cancel sequence from ``session-start``
    through ``session-end``.
    """
    session_start: dict[str, Any] = {
        "type": "session-start",
        "mode": "exercises",
        "exercises": exercises,
        "exercise_count": len(exercises),
        "seed": seed,
        "set_session": set_session,
    }
    if warm_up:
        session_start["warm_up"] = True
    await _send_event(ws, session_start)

    audio_task = asyncio.create_task(asyncio.to_thread(playback.play, samples, audio_params))

    started_at = datetime.now(timezone.utc)
    emitted_symbols: list[dict[str, Any]] = []

    try:
        cursor = 0.0
        for symbol, t_on, t_off, exercise_index, word_index, word in timeline:
            wait = t_on - cursor
            if wait > 0:
                await asyncio.sleep(wait)
            cursor = t_on
            entry = {
                "symbol": symbol,
                "t_on": t_on,
                "t_off": t_off,
                "exercise_index": exercise_index,
                "word_index": word_index,
                "word": word,
            }
            emitted_symbols.append(entry)
            await _send_event(ws, {"type": "symbol", **entry})

        await audio_task
        record_path = _write_koch_record(
            config_path=config_path,
            audio_params=audio_params,
            claimed=claimed,
            seed=seed,
            generation=generation,
            exercises=exercise_entries,
            symbols=emitted_symbols,
            started_at=started_at,
            warm_up=warm_up,
        )
        await _send_event(ws, {"type": "session-end"})
        return record_path

    except asyncio.CancelledError:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        audio_task.cancel()
        raise


async def _start_warmup_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
    *,
    set_session: int = 1,
    set_id: str = "",
) -> Path | None:
    """Play a warm-up Koch session — simplified pairs, no gear participation.

    Same audio and session lifecycle as :func:`_start_action`, but
    exercises are constrained to single 2-character words (symbol pairs)
    with a bias toward the learner's known confusion pairs. The record
    is flagged ``warm_up=True`` so it is excluded from gear evidence
    while still contributing to confusion-pair tracking.
    """
    audio_params = load_audio_parameters(config_path)
    claimed = load_claimed_symbols(config_path)

    if not claimed:
        await _send_event(ws, {"type": "error", "reason": "no-claimed-symbols"})
        return None

    save_directory = load_save_directory(config_path)
    claimed_set_key = " ".join(sorted(claimed))

    records = _iter_koch_records(save_directory)
    confusion = load_confusion_pairs(records, claimed_set_key=claimed_set_key)
    confusion_subs = confusion.get("substitutions", [])

    exercises, seed = _build_warmup_exercises(claimed, confusion_subs)

    exercise_entries = build_exercise_entries(
        exercises,
        scores=[10 * (i + 1) for i in range(len(exercises))],
        gears=[0] * len(exercises),
    )
    generation = build_generation_profile(
        claimed_set=claimed,
        candidate_count=len(exercises),
        exercise_count=len(exercises),
        gears=[0] * len(exercises),
    )
    generation["set_id"] = set_id
    generation["set_session"] = set_session

    samples, timeline, audio_shape = build_exercises_audio(
        exercises,
        audio_params,
        scaffold_break=False,
    )
    generation.update(audio_shape)

    return await _run_koch_session(
        ws,
        config_path,
        audio_params=audio_params,
        claimed=claimed,
        exercises=exercises,
        exercise_entries=exercise_entries,
        generation=generation,
        samples=samples,
        timeline=timeline,
        seed=seed,
        set_session=set_session,
        warm_up=True,
    )


async def _start_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
    *,
    set_session: int = 3,
    set_id: str = "",
) -> Path | None:
    """Play a short Koch Exercises session from the claimed set.

    The session is a fixed-count list of pseudo-word exercises produced
    by :func:`copy_653.sequence.generate_copy_exercises`. At the early
    Koch stages — where natural words are not available — grouping
    (intra-character vs inter-word spacing) is the difficulty knob, not
    speed; WPM and Farnsworth come from the audio config and are not
    altered here.

    Reads the claimed set and audio parameters fresh per call. Exercise
    structure is fixed at the page level (5 exercises, up to 3 elements
    each, words of 1–3 symbols) — not a session-config knob, so the
    learner cannot accidentally tune themselves out of the listening
    contract.

    Returns the path of the written koch-exercise record on natural
    end, or ``None`` on early-exit paths (no claimed symbols, failed
    write). The caller stashes the path so a later
    ``save-koch-answers`` can rewrite the file with learner answers.
    """
    audio_params = load_audio_parameters(config_path)
    claimed = load_claimed_symbols(config_path)

    if not claimed:
        # The default is KOCH_FIRST_PAIR; an empty claimed set means
        # the learner has actively cleared their config. Honest refusal
        # rather than synthesising silence (spec §1.5).
        await _send_event(ws, {"type": "error", "reason": "no-claimed-symbols"})
        return None

    # Resolve per-slot gears from prior evidence before generation. The
    # generator owns gear semantics; this call only decides "which gear"
    # by reading the recent record history for this exact claimed set.
    save_directory = load_save_directory(config_path)
    claimed_set_key = " ".join(sorted(claimed))
    gears, resolved_rst = _resolve_session_gears_and_rst(
        save_directory, claimed_set_key, exercise_count=5
    )
    rst_steps_for_session = {
        band: resolved_rst.get(band, (0, 0))
        for band, gear in enumerate(gears, start=1)
        if gear == MAX_GEAR
    }

    result = sequence.generate_copy_exercises(
        claimed_set=claimed,
        exercise_count=5,
        max_words=3,
        min_word_length=1,
        max_word_length=3,
        gears=gears,
        rst_steps=rst_steps_for_session or None,
    )
    # Prepend the fixed ``DE`` listening anchor (spec §2.5). Unlike the
    # uniform draw, this is deliberate structural framing — the same two
    # letters open every exercise so the learner enters the listening
    # frame from a known shape regardless of their claimed set.
    exercises = [f"DE {exercise}" for exercise in result.exercises]
    exercise_entries = build_exercise_entries(
        exercises,
        scores=result.scores,
        gears=gears,
        rst_draws=list(result.rst_draws) if result.rst_draws else None,
    )
    generation = build_generation_profile(
        claimed_set=claimed,
        candidate_count=result.candidate_count,
        exercise_count=len(exercises),
        gears=gears,
        rst_steps=rst_steps_for_session or None,
    )
    generation["set_id"] = set_id
    generation["set_session"] = set_session
    # Scaffold-break audio tracks the gear axis: it engages when every
    # band is at MAX_GEAR and disengages only when a band drops out.
    # This inherits the gear axis's hysteresis (4 consecutive low runs
    # to drop) so one imperfect copy under lead-in disruption does not
    # yank away the disruption the learner is practising through.
    scaffold_break = all(g >= MAX_GEAR for g in gears)
    rst_draws_for_audio: list[tuple[int | None, int | None]] | None = (
        list(result.rst_draws) if any(d != (None, None) for d in result.rst_draws) else None
    )
    samples, timeline, audio_shape = build_exercises_audio(
        exercises,
        audio_params,
        scaffold_break=scaffold_break,
        rng_seed=result.seed if scaffold_break else None,
        rst_draws=rst_draws_for_audio,
    )
    # Fold the assembly-time choices into the generation block so the
    # session record carries enough to replay the exact audio.
    generation.update(audio_shape)

    return await _run_koch_session(
        ws,
        config_path,
        audio_params=audio_params,
        claimed=claimed,
        exercises=exercises,
        exercise_entries=exercise_entries,
        generation=generation,
        samples=samples,
        timeline=timeline,
        seed=result.seed,
        set_session=set_session,
    )


async def _save_koch_answers_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
    pending_path: Path | None,
) -> bool:
    """Merge learner-typed answers into the most recently written
    koch-exercise record.

    Returns ``True`` on success so the caller can clear the pending
    path — a saved record cannot be saved again until the next session
    produces a new one. Returns ``False`` on validation or write
    failure (the error is already surfaced as a WS event).

    Validation lives here, not in the persistence layer, so the WS
    surface stays consistent: every learner-facing failure is an
    ``error`` event with a stable ``reason`` token. The
    ``answers`` list must be parallel to the record's ``exercises``;
    length mismatch is rejected per spec §1.5 rather than silently
    padded.
    """
    if pending_path is None:
        await _send_event(ws, {"type": "error", "reason": "no-pending-koch-record"})
        return False

    raw_answers = message.get("answers")
    if not isinstance(raw_answers, list) or not all(isinstance(a, str) for a in raw_answers):
        await _send_event(ws, {"type": "error", "reason": "invalid-answers"})
        return False

    try:
        exercise_count = _save_koch_answers(pending_path, list(raw_answers))
    except ValueError as exc:
        await _send_event(
            ws,
            {"type": "error", "reason": "answers-length-mismatch", "detail": str(exc)},
        )
        return False
    except FileNotFoundError:
        # The file existed when we recorded the pending path but is
        # gone now — likely a learner with two tabs racing, or a
        # cleanup script. Surface honestly.
        await _send_event(ws, {"type": "error", "reason": "pending-koch-record-missing"})
        return False

    await _send_event(
        ws,
        {
            "type": "koch-answers-saved",
            "answer_count": len(raw_answers),
            "exercise_count": exercise_count,
        },
    )
    return True


async def _broadcast_claimed_state(
    ws: WebSocketServerProtocol,
    claimed: tuple[str, ...],
    config_path: Path,
    *,
    set_is_fresh: bool,
) -> None:
    """Resolve readiness signals and push the claimed-symbols event."""
    save_directory = load_save_directory(config_path)
    claimed_set_key = " ".join(sorted(claimed))
    evidence_ready_for_next, ready_for_next = _koch_readiness_state(save_directory, claimed_set_key)
    ready_for_next_send = _next_send_symbol_readiness(save_directory, claimed_set_key)
    await _send_event(
        ws,
        _claimed_symbols_event(
            claimed,
            evidence_ready_for_next=evidence_ready_for_next,
            ready_for_next=ready_for_next,
            ready_for_next_send=ready_for_next_send,
            set_is_fresh=set_is_fresh,
        ),
    )


async def _claim_symbol_action(
    ws: WebSocketServerProtocol,
    symbol: str,
    config_path: Path,
    *,
    set_is_fresh: bool = True,
) -> None:
    """Append ``symbol`` to the claimed set and broadcast the new state.

    Idempotent: claiming a symbol already in the set is a no-op (still
    rebroadcasts, so a UI out of sync converges).

    Validation per spec §1.5: an unknown symbol surfaces as an
    ``error`` event without mutating the config.
    """
    if not isinstance(symbol, str) or len(symbol) != 1:
        await _send_event(ws, {"type": "error", "reason": "symbol-must-be-single-character"})
        return

    upper = symbol.upper()
    try:
        patterns.pattern_for(upper)
    except KeyError:
        await _send_event(ws, {"type": "error", "reason": "unknown-symbol", "symbol": upper})
        return

    claimed = load_claimed_symbols(config_path)
    if upper not in claimed:
        new_claimed = (*claimed, upper)
        save_claimed_symbols(new_claimed, config_path)
        claimed = new_claimed

    await _broadcast_claimed_state(ws, claimed, config_path, set_is_fresh=set_is_fresh)


async def _unclaim_symbol_action(
    ws: WebSocketServerProtocol,
    symbol: str,
    config_path: Path,
    *,
    set_is_fresh: bool = True,
) -> None:
    """Remove ``symbol`` from the claimed set and broadcast the new state.

    Idempotent: unclaiming a symbol not in the set is a no-op (still
    rebroadcasts, so a UI out of sync converges).

    The first two symbols in KOCH_ORDER (K, M) are the permanent starting
    pair and cannot be unclaimed — the engine requires at least two symbols
    to generate a session. Attempting to unclaim them surfaces an error.
    """
    if not isinstance(symbol, str) or len(symbol) != 1:
        await _send_event(ws, {"type": "error", "reason": "symbol-must-be-single-character"})
        return

    upper = symbol.upper()
    if upper in (patterns.KOCH_ORDER[0], patterns.KOCH_ORDER[1]):
        await _send_event(
            ws, {"type": "error", "reason": "cannot-unclaim-starting-pair", "symbol": upper}
        )
        return

    claimed = load_claimed_symbols(config_path)
    if upper in claimed:
        new_claimed = tuple(s for s in claimed if s != upper)
        save_claimed_symbols(new_claimed, config_path)
        claimed = new_claimed

    await _broadcast_claimed_state(ws, claimed, config_path, set_is_fresh=set_is_fresh)


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
    all_symbols: list[dict[str, Any]] = []
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
            all_symbols.append(entry)
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
