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
)
from copy_653.letters.sequence import ANCHORED_SYMBOLS, wav_path_for
from copy_653.letters.wav import load_wav
from copy_653.server.records import _write_recognition_record
from copy_653.server.wire_events import _send_event

logger = logging.getLogger(__name__)

EXERCISE_COUNT = 5
SYMBOLS_PER_EXERCISE = 5

GAP_AFTER_SAY_SECONDS = 0.5
GAP_BETWEEN_MORSE_REPEATS_SECONDS = 0.6
GAP_BETWEEN_SYMBOLS_SECONDS = 0.8
GAP_BETWEEN_EXERCISES_SECONDS = 2.0


def _play_samples(samples, sample_rate_hz: int, output_device: int | str | None) -> None:
    import sounddevice as sd

    sd.play(samples, samplerate=sample_rate_hz, device=output_device, blocking=True)


def _generate_recognition_exercises(
    claimed: tuple[str, ...],
    exercise_count: int = EXERCISE_COUNT,
    symbols_per_exercise: int = SYMBOLS_PER_EXERCISE,
    seed: int | None = None,
) -> tuple[list[list[str]], int]:
    concrete_seed = seed if seed is not None else random.Random().randint(0, 2**63 - 1)
    rng = random.Random(concrete_seed)
    exercises = [
        [rng.choice(claimed) for _ in range(symbols_per_exercise)] for _ in range(exercise_count)
    ]
    return exercises, concrete_seed


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

            for sym in exercise:
                upper = sym.upper()
                has_anchor = upper in ANCHORED_SYMBOLS

                if recognition_settings.say_before and has_anchor:
                    wav_samples, wav_rate = load_wav(wav_path_for(upper, anchors_dir))
                    await asyncio.to_thread(_play_samples, wav_samples, wav_rate, output_device)
                    await asyncio.sleep(GAP_AFTER_SAY_SECONDS)

                morse_samples = synth.synthesize_sequence([upper], audio_params)
                morse_samples = texture.add_receiver_bed(
                    morse_samples, audio_params, context=f"recognition:{upper}"
                )
                morse_rate = audio_params.sample_rate_hz

                t_on = time.monotonic() - start_mono
                for rep in range(recognition_settings.morse_count):
                    await asyncio.to_thread(_play_samples, morse_samples, morse_rate, output_device)
                    if rep < recognition_settings.morse_count - 1:
                        await asyncio.sleep(GAP_BETWEEN_MORSE_REPEATS_SECONDS)
                t_off = time.monotonic() - start_mono

                entry = {
                    "symbol": upper,
                    "t_on": round(t_on, 4),
                    "t_off": round(t_off, 4),
                    "exercise_index": ex_idx,
                }
                emitted_symbols.append(entry)
                await _send_event(ws, {"type": "symbol", **entry})

                await asyncio.sleep(recognition_settings.recognition_time_ms / 1000)

                if recognition_settings.say_after and has_anchor:
                    wav_samples, wav_rate = load_wav(wav_path_for(upper, anchors_dir))
                    await asyncio.to_thread(_play_samples, wav_samples, wav_rate, output_device)

                await asyncio.sleep(GAP_BETWEEN_SYMBOLS_SECONDS)

        exercise_entries = [
            {"index": i + 1, "target": " ".join(ex)} for i, ex in enumerate(exercises)
        ]
        generation: dict[str, Any] = {
            "set_id": set_id,
            "set_session": set_session,
            "claimed_set_key": " ".join(sorted(claimed)),
            "exercise_count": len(exercises),
            "symbols_per_exercise": SYMBOLS_PER_EXERCISE,
            "recognition": {
                "say_before": recognition_settings.say_before,
                "morse_count": recognition_settings.morse_count,
                "recognition_time_ms": recognition_settings.recognition_time_ms,
                "say_after": recognition_settings.say_after,
            },
        }

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
    exercises, seed = _generate_recognition_exercises(claimed)
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
    )
