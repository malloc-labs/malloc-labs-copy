"""Symbol Recognition session engine.

Per-symbol training flow: [optional Say Before NATO phonetic] →
[Morse × morse_count] → [silence for recognition_time_ms] →
[optional Say After NATO phonetic]. Sessions follow the 8×5 set
structure (no warm-up) and write records under ``recognition/``.

The playback uses the same segment-by-segment async pattern as
:mod:`copy_653.letters.sequence` — each audio piece is played via
``asyncio.to_thread`` so cancellation can take effect between segments.
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from websockets.server import WebSocketServerProtocol

from copy_653.audio import synth, texture
from copy_653.audio.parameters import AudioParameters
from copy_653.config import (
    RecognitionSettings,
    load_audio_parameters,
    load_claimed_symbols,
    load_recognition_settings,
    load_save_directory,
)
from copy_653.letters.sequence import ANCHORED_SYMBOLS, wav_path_for
from copy_653.letters.wav import load_wav
from copy_653.server.records import _write_recognition_record
from copy_653.server.records import _resolve_recognition_session_gears
from copy_653.server.wire_events import _send_event
from copy_653.sequence.recognition_analysis import (
    analyse_recognition_exercises,
    build_recognition_generation_profile,
)

logger = logging.getLogger(__name__)

EXERCISE_COUNT = 5
GEAR_0_SYMBOLS_PER_EXERCISE = 4
GEAR_1_WORDS_PER_EXERCISE = 1
GEAR_2_WORDS_PER_EXERCISE = 2
GEAR_3_WORDS_PER_EXERCISE = 1
GEAR_3_MIN_RECEIVER_BED = 2

GAP_AFTER_SAY_SECONDS = 0.5
GAP_BETWEEN_MORSE_REPEATS_SECONDS = 0.6
GAP_BETWEEN_SYMBOLS_SECONDS = 0.8
GAP_BETWEEN_EXERCISES_SECONDS = 2.0
DIAGNOSTIC_TAIL_AFTER_FINAL_COMPLETION_SECONDS = 3.0
RECOGNITION_FLOOR_BUFFER_SECONDS = 30.0


@dataclass
class ActiveRecognitionSession:
    ws: WebSocketServerProtocol
    config_path: Path
    audio_params: AudioParameters
    claimed: tuple[str, ...]
    recognition_settings: RecognitionSettings
    anchors_dir: Path
    seed: int
    set_session: int
    set_id: str
    gears: list[int]
    rng: random.Random
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    start_mono: float = field(default_factory=time.monotonic)
    exercises: list[dict[str, Any]] = field(default_factory=list)
    symbols: list[dict[str, Any]] = field(default_factory=list)
    completions: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)

    @property
    def gear(self) -> int:
        return self.gears[0] if self.gears else 0

    async def push_completion(self, payload: dict[str, Any]) -> None:
        await self.completions.put(payload)

    def append_late_voice_capture(self, exercise_index: int, entries: list[dict[str, Any]]) -> None:
        """Attach diagnostic-only recognizer finals to an analysed exercise.

        ``voice_capture`` remains the committed response used for
        progression. ``late_voice_capture`` records finals that arrived
        after that committed snapshot, so review/debugging can see what
        the application heard without inflating ICR evidence.
        """
        if exercise_index < 1 or exercise_index > len(self.exercises):
            return
        exercise = self.exercises[exercise_index - 1]
        late = exercise.setdefault("late_voice_capture", [])
        if isinstance(late, list):
            late.extend(entries)


def _play_samples(samples, sample_rate_hz: int, output_device: int | str | None) -> None:
    import sounddevice as sd

    sd.play(samples, samplerate=sample_rate_hz, device=output_device, blocking=True)


def _recognition_floor_samples(params: AudioParameters):
    import numpy as np

    frame_count = max(1, int(params.sample_rate_hz * RECOGNITION_FLOOR_BUFFER_SECONDS))
    silence = np.zeros(frame_count, dtype=np.float32)
    return texture.add_receiver_bed(
        silence,
        params,
        context="recognition:page-floor",
    )


def _play_recognition_receiver_bed_loop(
    params: AudioParameters,
    stop_event: threading.Event,
) -> None:
    if params.receiver_bed == 0:
        return

    import numpy as np
    import sounddevice as sd

    samples = _recognition_floor_samples(params)
    if len(samples) == 0:
        return

    position = 0

    def callback(outdata, frames, _time_info, _status):
        nonlocal position
        remaining = frames
        offset = 0
        while remaining > 0:
            take = min(remaining, len(samples) - position)
            outdata[offset : offset + take, 0] = samples[position : position + take]
            position = (position + take) % len(samples)
            offset += take
            remaining -= take

    with sd.OutputStream(
        samplerate=params.sample_rate_hz,
        device=params.output_device,
        channels=1,
        dtype=np.float32,
        callback=callback,
    ):
        stop_event.wait()


async def _run_recognition_receiver_bed_loop(config_path: Path) -> None:
    params = load_audio_parameters(config_path)
    if params.receiver_bed == 0:
        return
    stop_event = threading.Event()
    try:
        await asyncio.to_thread(_play_recognition_receiver_bed_loop, params, stop_event)
    except asyncio.CancelledError:
        stop_event.set()
        raise
    except Exception:
        logger.exception("recognition receiver bed playback failed")


def _generate_recognition_exercises(
    claimed: tuple[str, ...],
    *,
    gears: list[int],
    exercise_count: int = EXERCISE_COUNT,
    seed: int | None = None,
) -> tuple[list[list[str]], int]:
    concrete_seed = seed if seed is not None else random.Random().randint(0, 2**63 - 1)
    rng = random.Random(concrete_seed)
    exercises = []
    for idx in range(exercise_count):
        gear = gears[idx] if idx < len(gears) else 0
        exercises.append(_generate_recognition_exercise(claimed, gear=gear, rng=rng))
    return exercises, concrete_seed


def _new_recognition_seed(seed: int | None = None) -> tuple[random.Random, int]:
    concrete_seed = seed if seed is not None else random.Random().randint(0, 2**63 - 1)
    return random.Random(concrete_seed), concrete_seed


def _generate_recognition_exercise(
    claimed: tuple[str, ...],
    *,
    gear: int,
    rng: random.Random,
) -> list[str]:
    if gear >= 3:
        return [
            _random_word(claimed, rng, min_length=3, max_length=3)
            for _ in range(GEAR_3_WORDS_PER_EXERCISE)
        ]
    if gear >= 2:
        return [
            _random_word(claimed, rng, min_length=2, max_length=2)
            for _ in range(GEAR_2_WORDS_PER_EXERCISE)
        ]
    if gear == 1:
        return [
            _random_word(claimed, rng, min_length=2, max_length=2)
            for _ in range(GEAR_1_WORDS_PER_EXERCISE)
        ]
    count = GEAR_0_SYMBOLS_PER_EXERCISE
    return [rng.choice(claimed) for _ in range(count)]


def _random_word(
    claimed: tuple[str, ...],
    rng: random.Random,
    *,
    min_length: int = 1,
    max_length: int,
) -> str:
    length = rng.randint(min_length, max_length)
    return "".join(rng.choice(claimed) for _ in range(length))


def _recognition_kind_for_gear(gear: int) -> str:
    if gear >= 3:
        return "words"
    if gear >= 1:
        return "pairs"
    return "single-symbols"


def _say_after_for_slot(*, gear: int, exercise_index: int) -> bool:
    if gear <= 0:
        return exercise_index == 1
    return False


def _audio_params_for_gear(params: AudioParameters, gear: int) -> AudioParameters:
    if gear < 3 or params.receiver_bed >= GEAR_3_MIN_RECEIVER_BED:
        return params
    return replace(params, receiver_bed=GEAR_3_MIN_RECEIVER_BED)


def _recognition_answer_matches_target(answer: str, target: str) -> bool:
    return _compact_symbols(answer) == _compact_symbols(target)


def _compact_symbols(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


async def _run_recognition_session(session: ActiveRecognitionSession) -> Path | None:
    await _send_event(
        session.ws,
        {
            "type": "session-start",
            "mode": "recognition",
            "exercise_count": EXERCISE_COUNT,
            "seed": session.seed,
            "set_session": session.set_session,
            "gear": session.gear,
            "recognition_kind": _recognition_kind_for_gear(session.gear),
        },
    )

    try:
        next_exercise: list[str] | None = None
        for ex_idx in range(1, EXERCISE_COUNT + 1):
            if ex_idx > 1:
                await asyncio.sleep(GAP_BETWEEN_EXERCISES_SECONDS)

            exercise = next_exercise or _generate_recognition_exercise(
                session.claimed,
                gear=session.gear,
                rng=session.rng,
            )
            exercise_entry = _recognition_exercise_entry(ex_idx, exercise, session.gear)
            session.exercises.append(exercise_entry)
            await _send_event(
                session.ws,
                {
                    "type": "recognition-exercise-start",
                    "exercise_index": ex_idx,
                    "exercise_count": EXERCISE_COUNT,
                },
            )
            await _play_recognition_exercise(session, exercise=exercise, exercise_index=ex_idx)
            await _send_event(
                session.ws,
                {"type": "recognition-exercise-end", "exercise_index": ex_idx},
            )

            completion = await _next_exercise_completion(session, ex_idx)
            answer = str(completion["answer"])
            voice_capture = completion.get("voice_capture")
            exercise_entry["answer"] = answer
            exercise_entry["voice_capture"] = (
                voice_capture if isinstance(voice_capture, list) else []
            )

            analysed = analyse_recognition_exercises([exercise_entry], session.symbols)
            session.exercises[-1] = analysed[0]
            target = str(exercise_entry["target"])
            next_exercise = None if _recognition_answer_matches_target(answer, target) else exercise

        await asyncio.sleep(DIAGNOSTIC_TAIL_AFTER_FINAL_COMPLETION_SECONDS)

        generation = build_recognition_generation_profile(
            claimed_set=session.claimed,
            exercise_count=EXERCISE_COUNT,
            gears=session.gears,
        )
        generation.update(
            {
                "set_id": session.set_id,
                "set_session": session.set_session,
                "recognition": {
                    "say_before": session.recognition_settings.say_before,
                    "morse_count": session.recognition_settings.morse_count,
                    "recognition_time_ms": session.recognition_settings.recognition_time_ms,
                    "say_after": session.recognition_settings.say_after,
                },
            }
        )

        record_path = _write_recognition_record(
            config_path=session.config_path,
            audio_params=session.audio_params,
            claimed=session.claimed,
            seed=session.seed,
            generation=generation,
            exercises=session.exercises,
            symbols=session.symbols,
            started_at=session.started_at,
        )
        await _send_event(session.ws, {"type": "session-end"})
        return record_path

    except asyncio.CancelledError:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        raise


def _recognition_exercise_entry(index: int, exercise: list[str], gear: int) -> dict[str, Any]:
    return {
        "index": index,
        "target": " ".join(exercise),
        "burden_band": index,
        "gear": gear,
        "recognition_kind": _recognition_kind_for_gear(gear),
    }


async def _play_recognition_exercise(
    session: ActiveRecognitionSession,
    *,
    exercise: list[str],
    exercise_index: int,
) -> None:
    output_device = session.audio_params.output_device
    word_audio_params = _audio_params_for_gear(session.audio_params, session.gear)
    for word_index, raw_word in enumerate(exercise, start=1):
        word = raw_word.upper()
        symbols_in_word = list(word)
        for upper in symbols_in_word:
            has_anchor = upper in ANCHORED_SYMBOLS
            should_say_after = (
                session.recognition_settings.say_after
                and has_anchor
                and _say_after_for_slot(gear=session.gear, exercise_index=exercise_index)
            )

            if session.recognition_settings.say_before and has_anchor:
                wav_samples, wav_rate = load_wav(wav_path_for(upper, session.anchors_dir))
                await asyncio.to_thread(
                    _play_samples,
                    wav_samples,
                    wav_rate,
                    output_device,
                )
                await asyncio.sleep(GAP_AFTER_SAY_SECONDS)

        morse_samples = synth.synthesize_words([word], word_audio_params)
        morse_rate = word_audio_params.sample_rate_hz

        t_on = time.monotonic() - session.start_mono
        for rep in range(session.recognition_settings.morse_count):
            await asyncio.to_thread(
                _play_samples,
                morse_samples,
                morse_rate,
                output_device,
            )
            if rep < session.recognition_settings.morse_count - 1:
                await asyncio.sleep(GAP_BETWEEN_MORSE_REPEATS_SECONDS)
        word_t_off = time.monotonic() - session.start_mono

        timeline = synth.compute_word_timeline([word], word_audio_params)
        if not timeline:
            timeline = [
                (symbol, 0.0, word_t_off - t_on, word_index, word) for symbol in symbols_in_word
            ]
        for symbol, rel_on, rel_off, _rel_word_index, _rel_word in timeline:
            entry = {
                "symbol": symbol,
                "t_on": round(t_on + rel_on, 4),
                "t_off": round(t_on + rel_off, 4),
                "exercise_index": exercise_index,
                "word_index": word_index,
                "word": word,
            }
            session.symbols.append(entry)
            await _send_event(session.ws, {"type": "symbol", **entry})

        await asyncio.sleep(session.recognition_settings.recognition_time_ms / 1000)

        if len(symbols_in_word) == 1 and should_say_after:
            wav_samples, wav_rate = load_wav(wav_path_for(symbols_in_word[0], session.anchors_dir))
            await asyncio.to_thread(
                _play_samples,
                wav_samples,
                wav_rate,
                output_device,
            )

        await asyncio.sleep(GAP_BETWEEN_SYMBOLS_SECONDS)


async def _next_exercise_completion(
    session: ActiveRecognitionSession,
    exercise_index: int,
) -> dict[str, Any]:
    while True:
        completion = await session.completions.get()
        if completion.get("exercise_index") == exercise_index:
            return completion
        await _send_event(
            session.ws,
            {
                "type": "error",
                "reason": "invalid-recognition-exercise-index",
            },
        )


def _coerce_recognition_exercise_completion(message: dict[str, Any]) -> dict[str, Any] | None:
    exercise_index = message.get("exercise_index")
    answer = message.get("answer")
    voice_capture = message.get("voice_capture")
    if not isinstance(exercise_index, int) or isinstance(exercise_index, bool):
        return None
    if not isinstance(answer, str):
        return None
    if not isinstance(voice_capture, list) or not all(
        isinstance(item, dict) for item in voice_capture
    ):
        return None
    return {
        "exercise_index": exercise_index,
        "answer": answer,
        "voice_capture": voice_capture,
    }


def _coerce_recognition_diagnostic(message: dict[str, Any]) -> dict[str, Any] | None:
    exercise_index = message.get("exercise_index")
    late_voice_capture = message.get("late_voice_capture")
    if not isinstance(exercise_index, int) or isinstance(exercise_index, bool):
        return None
    if not isinstance(late_voice_capture, list) or not all(
        isinstance(item, dict) for item in late_voice_capture
    ):
        return None
    return {
        "exercise_index": exercise_index,
        "late_voice_capture": late_voice_capture,
    }


async def _start_recognition_action(
    ws: WebSocketServerProtocol,
    config_path: Path,
    *,
    set_session: int,
    set_id: str,
    anchors_dir: Path,
) -> Path | None:
    audio_params = load_audio_parameters(config_path)
    claimed = load_claimed_symbols(config_path)
    if not claimed:
        await _send_event(ws, {"type": "error", "reason": "no-claimed-symbols"})
        return None
    recognition_settings = load_recognition_settings(config_path)
    claimed_set_key = " ".join(sorted(claimed))
    save_directory = load_save_directory(config_path)
    gears = _resolve_recognition_session_gears(
        save_directory,
        claimed_set_key,
        exercise_count=EXERCISE_COUNT,
        set_id=set_id,
        set_session=set_session,
    )
    rng, seed = _new_recognition_seed()
    return ActiveRecognitionSession(
        ws=ws,
        config_path=config_path,
        audio_params=audio_params,
        claimed=claimed,
        recognition_settings=recognition_settings,
        anchors_dir=anchors_dir,
        seed=seed,
        set_session=set_session,
        set_id=set_id,
        gears=gears,
        rng=rng,
    )
