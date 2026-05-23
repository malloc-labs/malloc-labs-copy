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
import base64
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from websockets.server import WebSocketServerProtocol

from copy_653 import sequence
from copy_653.audio import patterns, playback, synth, texture, timing
from copy_653.audio.parameters import AudioParameters
from copy_653.audio.wav import encode_pcm16_wav
from copy_653.config import (
    KeyerSettings,
    load_audio_parameters,
    load_claimed_symbols,
    load_developer_settings,
    load_keyer_settings,
    load_letters_config,
    load_save_directory,
    save_audio_timing,
    save_claimed_symbols,
    save_developer_settings,
    save_keyer_settings,
    save_save_directory,
)
from copy_653.server.exercises_audio import build_exercises_audio
from copy_653.letters import (
    play_letter_sequence,
    play_morse_sequence,
)
from copy_653.midi import (
    KeyDecoder,
    KeyElementAssembler,
    MidiNoteEvent,
    iter_midi_note_events,
)
from copy_653.server.records import (
    _ActiveCadenceSession,
    _ActiveCopyKeySession,
    _next_cadence_run_index,
    _next_copy_key_run_index,
    _next_send_symbol_readiness,
    _next_symbol_evidence,
    _next_symbol_readiness,
    _resolve_cadence_session_gears,
    _resolve_copy_key_session_gears,
    _resolve_session_gears,
    _resolve_session_rst_steps,
    _save_koch_answers,
    _write_koch_record,
)
from copy_653.server.test_message_audio import build_marconi_test_message
from copy_653.server.validation import (
    _audio_params_from_settings_message,
    _optional_bool,
    _optional_bounded_int,
    _optional_non_empty_string,
    _optional_positive_int,
    _strict_positive_int,
)
from copy_653.server.wire_events import (
    _audio_settings_event_from_params,
    _claimed_symbols_event,
    _key_event_event,
    _key_input_start_event,
    _send_event,
    _sent_symbol_event,
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
)

logger = logging.getLogger(__name__)

# Divisible by 3 so every non-final base64 chunk can be concatenated safely.
WAV_EXPORT_CHUNK_SIZE = 245_760

KeyNoteSource = Callable[[threading.Event], Iterator[MidiNoteEvent]]


async def _push_key_note_event(
    ws: WebSocketServerProtocol,
    item: MidiNoteEvent,
    *,
    settings: KeyerSettings,
    audio_params: AudioParameters,
    assembler: KeyElementAssembler,
    decoder: KeyDecoder,
    recorder: Callable[[dict[str, Any]], None] | None = None,
) -> bool:
    """Apply one note event to the key decoder and emit any resulting events.

    Returns ``True`` if this event completed a key element (a note-off that
    closed an active note-on). Callers use the return value to gate the
    character-gap flush timer so it never fires mid-stroke between a
    note-on and its matching note-off.

    If ``recorder`` is provided, every event payload sent to the client
    is also handed to it. Used by the Cadence session recorder to
    accumulate sent symbols and raw MIDI events.
    """
    element = assembler.push(item, settings)
    key_event = _key_event_event(item, settings, audio_params, element)
    if key_event is not None:
        await _send_event(ws, key_event)
        if recorder is not None:
            recorder(key_event)
    if element is None:
        return False

    try:
        decoded = decoder.push(element)
    except ValueError as exc:
        await _send_event(
            ws,
            {"type": "error", "reason": "key-input-decode-failed", "detail": str(exc)},
        )
        decoder.reset()
        return True
    if decoded is not None:
        sent_event = _sent_symbol_event(decoded)
        await _send_event(ws, sent_event)
        if recorder is not None:
            recorder(sent_event)
    return True


async def _start_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
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
    gears = _resolve_session_gears(save_directory, claimed_set_key, exercise_count=5)
    # The RST sub-axis is per-band, scoped to bands at MAX_GEAR for this
    # session. Bands below MAX_GEAR contribute no entry, which the
    # generator and audio layer both read as "use the configured S/T".
    rst_steps_for_session: dict[int, tuple[int, int]] = {}
    if any(g == MAX_GEAR for g in gears):
        resolved_rst = _resolve_session_rst_steps(save_directory, claimed_set_key)
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

    await _send_event(
        ws,
        {
            "type": "session-start",
            "mode": "exercises",
            "exercises": exercises,
            "exercise_count": len(exercises),
            "seed": result.seed,
        },
    )

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

        # Wait for the audio thread to actually finish before declaring the
        # session ended — premature end-of-session would lie about what the
        # learner is hearing (§1.5).
        await audio_task
        record_path = _write_koch_record(
            config_path=config_path,
            audio_params=audio_params,
            claimed=claimed,
            seed=result.seed,
            generation=generation,
            exercises=exercise_entries,
            symbols=emitted_symbols,
            started_at=started_at,
        )
        await _send_event(ws, {"type": "session-end"})
        return record_path

    except asyncio.CancelledError:
        # Stop was requested. Signal PortAudio to abort the current stream
        # immediately — sd.stop() is the only way to interrupt a blocking
        # sd.play() running in a thread (asyncio task cancellation alone
        # does not reach into the thread).
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass  # No audio device or sounddevice not installed — ignore
        audio_task.cancel()
        raise  # Re-raise so _run_session's handler sends session-end


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


async def _claim_symbol_action(
    ws: WebSocketServerProtocol,
    symbol: str,
    config_path: Path,
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

    save_directory = load_save_directory(config_path)
    claimed_set_key = " ".join(sorted(claimed))
    evidence_ready_for_next = _next_symbol_evidence(save_directory, claimed_set_key)
    ready_for_next = _next_symbol_readiness(save_directory, claimed_set_key)
    ready_for_next_send = _next_send_symbol_readiness(save_directory, claimed_set_key)
    await _send_event(
        ws,
        _claimed_symbols_event(
            claimed,
            evidence_ready_for_next=evidence_ready_for_next,
            ready_for_next=ready_for_next,
            ready_for_next_send=ready_for_next_send,
        ),
    )


async def _unclaim_symbol_action(
    ws: WebSocketServerProtocol,
    symbol: str,
    config_path: Path,
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

    save_directory = load_save_directory(config_path)
    claimed_set_key = " ".join(sorted(claimed))
    evidence_ready_for_next = _next_symbol_evidence(save_directory, claimed_set_key)
    ready_for_next = _next_symbol_readiness(save_directory, claimed_set_key)
    ready_for_next_send = _next_send_symbol_readiness(save_directory, claimed_set_key)
    await _send_event(
        ws,
        _claimed_symbols_event(
            claimed,
            evidence_ready_for_next=evidence_ready_for_next,
            ready_for_next=ready_for_next,
            ready_for_next_send=ready_for_next_send,
        ),
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

    Generates short head-copy exercises (single words, 1-3 symbols,
    max 2 words / 5 total symbols), synthesises the audio for each,
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
        symbols=all_symbols,
    )
    session._per_exercise_audio = per_exercise_audio
    return session


async def _play_copy_key_exercise(
    ws: WebSocketServerProtocol,
    session: _ActiveCopyKeySession,
    exercise_index: int,
) -> None:
    """Play one pre-rendered Copy Key exercise and emit symbol events."""
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


async def _get_audio_settings_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
) -> None:
    params = load_audio_parameters(config_path)
    keyer_settings = load_keyer_settings(config_path)
    developer_settings = load_developer_settings(config_path)
    save_directory = load_save_directory(config_path)
    await _send_event(
        ws,
        _audio_settings_event_from_params(
            params, keyer_settings, developer_settings, save_directory
        ),
    )


async def _set_audio_settings_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
    config_path: Path,
) -> None:
    try:
        character_wpm = _strict_positive_int(message.get("character_wpm"), "character_wpm")
        effective_wpm = _strict_positive_int(message.get("effective_wpm"), "effective_wpm")
        tone_shape = _optional_bounded_int(
            message.get("tone_shape"),
            "tone_shape",
            texture.MIN_TONE_SHAPE,
            texture.MAX_TONE_SHAPE,
        )
        receiver_bed = _optional_bounded_int(
            message.get("receiver_bed"),
            "receiver_bed",
            texture.MIN_RECEIVER_BED,
            texture.MAX_RECEIVER_BED,
        )
        cadence_variation = _optional_bounded_int(
            message.get("cadence_variation"),
            "cadence_variation",
            texture.MIN_CADENCE_VARIATION,
            texture.MAX_CADENCE_VARIATION,
        )
        keyer_mode = _optional_non_empty_string(
            message.get("keyer_mode"),
            "keyer_mode",
        )
        hh_clear_enabled = _optional_bool(
            message.get("hh_clear_enabled"),
            "hh_clear_enabled",
        )
        save_directory_input = _optional_non_empty_string(
            message.get("save_directory"),
            "save_directory",
        )
        params = save_audio_timing(
            character_speed_wpm=character_wpm,
            effective_speed_wpm=effective_wpm,
            tone_shape=tone_shape,
            receiver_bed=receiver_bed,
            cadence_variation=cadence_variation,
            path=config_path,
        )
        if keyer_mode is not None:
            keyer_settings = save_keyer_settings(
                keyer_mode=keyer_mode,
                path=config_path,
            )
        else:
            keyer_settings = load_keyer_settings(config_path)
        if hh_clear_enabled is not None:
            developer_settings = save_developer_settings(
                hh_clear_enabled=hh_clear_enabled,
                path=config_path,
            )
        else:
            developer_settings = load_developer_settings(config_path)
        if save_directory_input is not None:
            save_directory = save_save_directory(save_directory_input, path=config_path)
        else:
            save_directory = load_save_directory(config_path)
    except ValueError as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "invalid-audio-settings",
                "detail": str(exc),
            },
        )
        return

    await _send_event(
        ws,
        _audio_settings_event_from_params(
            params, keyer_settings, developer_settings, save_directory
        ),
    )


async def _play_test_message_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
) -> None:
    try:
        params = _audio_params_from_settings_message(message)
    except ValueError as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "invalid-test-message-settings",
                "detail": str(exc),
            },
        )
        return

    await _send_event(ws, {"type": "test-message-start"})
    try:
        await asyncio.to_thread(playback.play, build_marconi_test_message(params), params)
    except asyncio.CancelledError:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        raise
    except Exception as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "test-message-playback-failed",
                "detail": str(exc),
            },
        )
        raise
    await _send_event(ws, {"type": "test-message-end"})


async def _save_test_message_action(
    ws: WebSocketServerProtocol,
    message: dict[str, Any],
) -> None:
    try:
        params = _audio_params_from_settings_message(message)
        wav_bytes = await asyncio.to_thread(
            lambda: encode_pcm16_wav(build_marconi_test_message(params), params.sample_rate_hz)
        )
    except ValueError as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "invalid-test-message-settings",
                "detail": str(exc),
            },
        )
        return

    filename = "copy-653-marconi-test-message.wav"
    await _send_event(
        ws,
        {
            "type": "test-message-wav-start",
            "filename": filename,
            "byte_length": len(wav_bytes),
        },
    )
    for start in range(0, len(wav_bytes), WAV_EXPORT_CHUNK_SIZE):
        encoded = base64.b64encode(wav_bytes[start : start + WAV_EXPORT_CHUNK_SIZE]).decode("ascii")
        await _send_event(ws, {"type": "test-message-wav-chunk", "data": encoded})
    await _send_event(ws, {"type": "test-message-wav-end", "filename": filename})


async def _run_key_input_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
    note_source: KeyNoteSource | None = None,
    recorder: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Receive Trinkey MIDI note events, decode symbols, and push them to the page."""
    try:
        settings = load_keyer_settings(config_path)
        audio_params = load_audio_parameters(config_path)
    except ValueError as exc:
        await _send_event(ws, {"type": "error", "reason": "invalid-config", "detail": str(exc)})
        return

    decoder = KeyDecoder(
        dit_seconds=timing.dit_seconds(audio_params.character_speed_wpm),
        character_gap_seconds=timing.send_inter_character_seconds(audio_params.character_speed_wpm),
        word_gap_seconds=timing.send_inter_word_seconds(audio_params.character_speed_wpm),
    )
    assembler = KeyElementAssembler()
    source = note_source or (
        lambda stop: iter_midi_note_events(port_name=settings.input_name, stop_event=stop)
    )
    queue: asyncio.Queue[MidiNoteEvent | BaseException | None] = asyncio.Queue()
    stop_event = threading.Event()
    loop = asyncio.get_running_loop()

    def _queue_from_thread(item: MidiNoteEvent | BaseException | None) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:
            pass

    def _read_midi() -> None:
        try:
            for note_event in source(stop_event):
                if stop_event.is_set():
                    break
                _queue_from_thread(note_event)
        except BaseException as exc:
            _queue_from_thread(exc)
        finally:
            _queue_from_thread(None)

    thread = threading.Thread(target=_read_midi, name="copy-653-key-midi", daemon=True)
    thread.start()
    character_gap_seconds = timing.send_inter_character_seconds(audio_params.character_speed_wpm)

    await _send_event(ws, _key_input_start_event(settings, audio_params))

    # Deadline (loop.time) for the next character-gap flush. ``None`` means no
    # element is awaiting flush (we're either idle or mid-stroke between a
    # note-on and its note-off). Rearming this on every event would race the
    # next note-off and split a single character into two symbols.
    flush_deadline: float | None = None

    try:
        while True:
            if flush_deadline is None:
                item = await queue.get()
            else:
                timeout = max(0.0, flush_deadline - loop.time())
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    await _flush_key_symbol(ws, decoder, recorder)
                    flush_deadline = None
                    continue

            if item is None:
                await _flush_key_symbol(ws, decoder, recorder)
                return
            if isinstance(item, BaseException):
                reason = (
                    "key-input-unavailable" if isinstance(item, ImportError) else "key-input-failed"
                )
                await _send_event(ws, {"type": "error", "reason": reason, "detail": str(item)})
                return

            formed_element = await _push_key_note_event(
                ws,
                item,
                settings=settings,
                audio_params=audio_params,
                assembler=assembler,
                decoder=decoder,
                recorder=recorder,
            )
            if formed_element:
                flush_deadline = loop.time() + character_gap_seconds
            else:
                # Note-on: element in progress. Disarm the flush so it can't
                # fire between this note-on and its matching note-off.
                flush_deadline = None
    finally:
        stop_event.set()
        await asyncio.to_thread(thread.join, 1.0)


async def _flush_key_symbol(
    ws: WebSocketServerProtocol,
    decoder: KeyDecoder,
    recorder: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Force a flush of any pending marks; the caller has already waited
    the character gap externally (timer task or wait_for timeout).

    ``recorder`` mirrors :func:`_push_key_note_event`'s contract: when
    provided, the sent-symbol payload is also handed to it so the
    Cadence session record captures timer-flushed symbols (i.e. the
    last symbol a learner keys, or any symbol finalised by silence
    rather than by the next stroke).
    """
    decoded = decoder.flush_pending()
    if decoded is not None:
        sent_event = _sent_symbol_event(decoded)
        await _send_event(ws, sent_event)
        if recorder is not None:
            recorder(sent_event)


async def _run_morse_repeat(
    ws: WebSocketServerProtocol,
    symbol: str,
    repeats: int,
    config_path: Path,
) -> None:
    """Play bare Morse for ``symbol`` ``repeats`` times. Emits start/end frames.

    Used by the Cadence page's Alt+character preview keybind. Reads
    audio params fresh so a learner who edits WPM mid-session hears the
    change on the next preview.
    """
    audio_params = load_audio_parameters(config_path)

    await _send_event(ws, {"type": "morse-repeat-start", "symbol": symbol, "repeats": repeats})
    try:
        await play_morse_sequence(symbol, audio_params, repeats=repeats)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "morse-repeat-failed",
                "symbol": symbol,
                "detail": str(exc),
            },
        )
        raise
    await _send_event(ws, {"type": "morse-repeat-end", "symbol": symbol})


async def _run_letter_sequence(
    ws: WebSocketServerProtocol,
    symbol: str,
    config_path: Path,
    anchors_dir: Path,
) -> None:
    """Send ``letter-start``, play the sequence, send ``letter-end``.

    Reads audio and letters config fresh per call (per the project's
    no-caching contract — the learner's hand-edited config takes
    effect immediately). Any exception during playback surfaces as an
    ``error`` event then re-raises so the caller's task records it.

    On :class:`asyncio.CancelledError` (a new ``play-letter`` arrived),
    no terminal event is sent — the new sequence's ``letter-start`` is
    the authoritative new state.
    """
    audio_params = load_audio_parameters(config_path)
    letters_config = load_letters_config(config_path)

    await _send_event(ws, {"type": "letter-start", "symbol": symbol})
    try:
        await play_letter_sequence(symbol, audio_params, letters_config, anchors_dir)
    except asyncio.CancelledError:
        # Superseded by another play-letter; the new task already sent
        # its own letter-start.
        raise
    except Exception as exc:
        await _send_event(
            ws,
            {
                "type": "error",
                "reason": "letter-playback-failed",
                "symbol": symbol,
                "detail": str(exc),
            },
        )
        raise
    await _send_event(ws, {"type": "letter-end", "symbol": symbol})
