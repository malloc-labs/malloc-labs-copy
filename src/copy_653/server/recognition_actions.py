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
import time
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
from copy_653.sequence.recognition_analysis import build_recognition_generation_profile

logger = logging.getLogger(__name__)

EXERCISE_COUNT = 5
GEAR_0_SYMBOLS_PER_EXERCISE = 4
GEAR_1_SYMBOLS_PER_EXERCISE = 4
GEAR_2_WORDS_PER_EXERCISE = 2
GEAR_3_WORDS_PER_EXERCISE = 2
GEAR_3_MIN_RECEIVER_BED = 2

GAP_AFTER_SAY_SECONDS = 0.5
GAP_BETWEEN_MORSE_REPEATS_SECONDS = 0.6
GAP_BETWEEN_SYMBOLS_SECONDS = 0.8
GAP_BETWEEN_EXERCISES_SECONDS = 2.0


def _play_samples(samples, sample_rate_hz: int, output_device: int | str | None) -> None:
    import sounddevice as sd

    sd.play(samples, samplerate=sample_rate_hz, device=output_device, blocking=True)


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


def _generate_recognition_exercise(
    claimed: tuple[str, ...],
    *,
    gear: int,
    rng: random.Random,
) -> list[str]:
    if gear >= 3:
        return [_random_word(claimed, rng, max_length=3) for _ in range(GEAR_3_WORDS_PER_EXERCISE)]
    if gear >= 2:
        return [
            _random_word(claimed, rng, min_length=2, max_length=2)
            for _ in range(GEAR_2_WORDS_PER_EXERCISE)
        ]
    count = GEAR_1_SYMBOLS_PER_EXERCISE if gear == 1 else GEAR_0_SYMBOLS_PER_EXERCISE
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
    if gear >= 2:
        return "pairs"
    return "single-symbols"


def _say_after_for_slot(*, gear: int, exercise_index: int) -> bool:
    if gear <= 0:
        return True
    if gear == 1:
        return exercise_index <= 2
    return False


def _audio_params_for_gear(params: AudioParameters, gear: int) -> AudioParameters:
    if gear < 3 or params.receiver_bed >= GEAR_3_MIN_RECEIVER_BED:
        return params
    return replace(params, receiver_bed=GEAR_3_MIN_RECEIVER_BED)


async def _run_recognition_session(
    ws: WebSocketServerProtocol,
    config_path: Path,
    *,
    audio_params: AudioParameters,
    claimed: tuple[str, ...],
    exercises: list[list[str]],
    recognition_settings: RecognitionSettings,
    anchors_dir: Path,
    seed: int,
    set_session: int,
    set_id: str,
    gears: list[int],
) -> Path | None:
    exercise_strings = [" ".join(ex) for ex in exercises]
    await _send_event(
        ws,
        {
            "type": "session-start",
            "mode": "recognition",
            "exercises": exercise_strings,
            "exercise_count": len(exercises),
            "seed": seed,
            "set_session": set_session,
        },
    )

    started_at = datetime.now(timezone.utc)
    start_mono = time.monotonic()
    emitted_symbols: list[dict[str, Any]] = []
    output_device = audio_params.output_device

    try:
        for ex_idx, exercise in enumerate(exercises, 1):
            if ex_idx > 1:
                await asyncio.sleep(GAP_BETWEEN_EXERCISES_SECONDS)

            gear = gears[ex_idx - 1] if ex_idx - 1 < len(gears) else 0
            word_audio_params = _audio_params_for_gear(audio_params, gear)
            for word_index, raw_word in enumerate(exercise, start=1):
                word = raw_word.upper()
                symbols_in_word = list(word)
                for upper in symbols_in_word:
                    has_anchor = upper in ANCHORED_SYMBOLS
                    should_say_after = (
                        recognition_settings.say_after
                        and has_anchor
                        and _say_after_for_slot(gear=gear, exercise_index=ex_idx)
                    )

                    if recognition_settings.say_before and has_anchor:
                        wav_samples, wav_rate = load_wav(wav_path_for(upper, anchors_dir))
                        await asyncio.to_thread(
                            _play_samples,
                            wav_samples,
                            wav_rate,
                            output_device,
                        )
                        await asyncio.sleep(GAP_AFTER_SAY_SECONDS)

                morse_samples = synth.synthesize_words([word], word_audio_params)
                morse_samples = texture.add_receiver_bed(
                    morse_samples,
                    word_audio_params,
                    context=f"recognition:g{gear}:{word}",
                )
                morse_rate = word_audio_params.sample_rate_hz

                t_on = time.monotonic() - start_mono
                for rep in range(recognition_settings.morse_count):
                    await asyncio.to_thread(
                        _play_samples,
                        morse_samples,
                        morse_rate,
                        output_device,
                    )
                    if rep < recognition_settings.morse_count - 1:
                        await asyncio.sleep(GAP_BETWEEN_MORSE_REPEATS_SECONDS)
                word_t_off = time.monotonic() - start_mono

                timeline = synth.compute_word_timeline([word], word_audio_params)
                if not timeline:
                    timeline = [
                        (symbol, 0.0, word_t_off - t_on, word_index, word)
                        for symbol in symbols_in_word
                    ]
                for symbol, rel_on, rel_off, _rel_word_index, _rel_word in timeline:
                    entry = {
                        "symbol": symbol,
                        "t_on": round(t_on + rel_on, 4),
                        "t_off": round(t_on + rel_off, 4),
                        "exercise_index": ex_idx,
                        "word_index": word_index,
                        "word": word,
                    }
                    emitted_symbols.append(entry)
                    await _send_event(ws, {"type": "symbol", **entry})

                await asyncio.sleep(recognition_settings.recognition_time_ms / 1000)

                if len(symbols_in_word) == 1 and should_say_after:
                    wav_samples, wav_rate = load_wav(wav_path_for(symbols_in_word[0], anchors_dir))
                    await asyncio.to_thread(
                        _play_samples,
                        wav_samples,
                        wav_rate,
                        output_device,
                    )

                await asyncio.sleep(GAP_BETWEEN_SYMBOLS_SECONDS)

        exercise_entries = []
        for i, ex in enumerate(exercises):
            gear = gears[i] if i < len(gears) else 0
            exercise_entries.append(
                {
                    "index": i + 1,
                    "target": " ".join(ex),
                    "burden_band": i + 1,
                    "gear": gear,
                    "recognition_kind": _recognition_kind_for_gear(gear),
                }
            )
        generation = build_recognition_generation_profile(
            claimed_set=claimed,
            exercise_count=len(exercises),
            gears=gears,
        )
        generation.update(
            {
                "set_id": set_id,
                "set_session": set_session,
                "recognition": {
                    "say_before": recognition_settings.say_before,
                    "morse_count": recognition_settings.morse_count,
                    "recognition_time_ms": recognition_settings.recognition_time_ms,
                    "say_after": recognition_settings.say_after,
                },
            }
        )

        record_path = _write_recognition_record(
            config_path=config_path,
            audio_params=audio_params,
            claimed=claimed,
            seed=seed,
            generation=generation,
            exercises=exercise_entries,
            symbols=emitted_symbols,
            started_at=started_at,
        )
        await _send_event(ws, {"type": "session-end"})
        return record_path

    except asyncio.CancelledError:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
        raise


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
    )
    exercises, seed = _generate_recognition_exercises(claimed, gears=gears)
    return await _run_recognition_session(
        ws,
        config_path,
        audio_params=audio_params,
        claimed=claimed,
        exercises=exercises,
        recognition_settings=recognition_settings,
        anchors_dir=anchors_dir,
        seed=seed,
        set_session=set_session,
        set_id=set_id,
        gears=gears,
    )
