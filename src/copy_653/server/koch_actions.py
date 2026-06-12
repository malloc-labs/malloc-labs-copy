"""Koch exercise WebSocket actions."""

from __future__ import annotations

import asyncio
import random
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from websockets.server import WebSocketServerProtocol

from copy_653 import sequence
from copy_653.audio import playback
from copy_653.audio.parameters import AudioParameters
from copy_653.config import (
    load_audio_parameters,
    load_claimed_symbols,
    load_save_directory,
)
from copy_653.server.exercises_audio import build_exercises_audio
from copy_653.server.records import (
    _iter_koch_records,
    _resolve_session_gears_and_rst,
    _save_koch_answers,
    _write_koch_record,
)
from copy_653.server.wire_events import _send_event
from copy_653.sequence.exercise_analysis import (
    MAX_GEAR,
    build_exercise_entries,
    build_generation_profile,
    load_confusion_pairs,
)
from copy_653.sequence.listening_conditions import (
    KOCH_CHALLENGE_END_SESSION,
    KOCH_CHALLENGE_START_SESSION,
    KOCH_LISTENING_PROBE_VERSION,
    KOCH_PROBE_PHASE_CHALLENGE,
    KOCH_PROGRESSION_ROLE_SUPPORTING_GEAR_UP,
    LISTENING_CONDITION_TEXTURED,
    rst_fields_for_audio_params,
)


def _apply_koch_listening_probe_metadata(
    entries: list[dict[str, Any]],
    *,
    rst_draws: list[tuple[int | None, int | None]],
) -> list[dict[str, Any]]:
    """Tag Koch challenge rows as positive-only listening-condition evidence."""
    for entry in entries:
        index = entry.get("index")
        s_draw: int | None = None
        t_draw: int | None = None
        if isinstance(index, int) and not isinstance(index, bool) and 1 <= index <= len(rst_draws):
            s_draw, t_draw = rst_draws[index - 1]
        entry["listening_probe"] = KOCH_LISTENING_PROBE_VERSION
        entry["listening_condition"] = LISTENING_CONDITION_TEXTURED
        entry["probe_phase"] = KOCH_PROBE_PHASE_CHALLENGE
        entry["progression_role"] = KOCH_PROGRESSION_ROLE_SUPPORTING_GEAR_UP
        if s_draw is not None:
            entry["s"] = int(s_draw)
        if t_draw is not None:
            entry["t"] = int(t_draw)
    return entries


def _koch_challenge_rst_draws(
    audio_params: AudioParameters,
    *,
    exercise_count: int,
    seed: int,
) -> list[tuple[int, int]]:
    baseline = rst_fields_for_audio_params(audio_params)
    rng = random.Random(seed ^ 0x653)
    draws = []
    for _ in range(exercise_count):
        s_drop = rng.randint(1, 3)
        t_drop = rng.randint(1, 3)
        draws.append((max(1, baseline["s"] - s_drop), max(1, baseline["t"] - t_drop)))
    return draws


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
        "koch_set_session": set_session,
    }
    bands = generation.get("bands")
    if isinstance(bands, list):
        koch_gears: list[int] = []
        for band in bands:
            if not isinstance(band, dict):
                continue
            gear = band.get("gear")
            if isinstance(gear, int) and not isinstance(gear, bool):
                koch_gears.append(gear)
        if koch_gears:
            session_start["koch_gears"] = koch_gears
    probe = generation.get("listening_probe")
    if isinstance(probe, dict) and probe.get("version") == KOCH_LISTENING_PROBE_VERSION:
        condition = next(
            (
                entry.get("listening_condition")
                for entry in exercise_entries
                if isinstance(entry, dict) and entry.get("listening_condition")
            ),
            None,
        )
        if isinstance(condition, str):
            session_start["listening_condition"] = condition
            phase = probe.get("phase")
            if isinstance(phase, str):
                session_start["probe_phase"] = phase
    if warm_up:
        session_start["warm_up"] = True
        session_start["koch_warm_up"] = True
    else:
        session_start["koch_warm_up"] = False
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
    challenge_session = KOCH_CHALLENGE_START_SESSION <= set_session <= KOCH_CHALLENGE_END_SESSION
    gears, resolved_rst = _resolve_session_gears_and_rst(
        save_directory, claimed_set_key, exercise_count=5
    )
    if challenge_session:
        gears = [MAX_GEAR] * 5
    rst_steps_for_session = {
        band: resolved_rst.get(band, (0, 0))
        for band, gear in enumerate(gears, start=1)
        if gear == MAX_GEAR and not challenge_session
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
    rst_draws_for_audio: list[tuple[int | None, int | None]] | None
    if challenge_session:
        challenge_rst_draws = _koch_challenge_rst_draws(
            audio_params,
            exercise_count=len(exercises),
            seed=result.seed,
        )
        rst_draws_for_audio = list(challenge_rst_draws)
        _apply_koch_listening_probe_metadata(exercise_entries, rst_draws=challenge_rst_draws)
        generation["listening_probe"] = {
            "version": KOCH_LISTENING_PROBE_VERSION,
            "phase": KOCH_PROBE_PHASE_CHALLENGE,
            "sets": list(range(KOCH_CHALLENGE_START_SESSION, KOCH_CHALLENGE_END_SESSION + 1)),
            "condition": LISTENING_CONDITION_TEXTURED,
            "progression_role": KOCH_PROGRESSION_ROLE_SUPPORTING_GEAR_UP,
        }
        generation["progression_role"] = KOCH_PROGRESSION_ROLE_SUPPORTING_GEAR_UP
    else:
        rst_draws_for_audio = (
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
