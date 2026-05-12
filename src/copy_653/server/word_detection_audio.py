"""Word Detection audio assembly for the server.

This module owns the audio-domain part of Word Detection: combining optional
spoken prompts with synthesized Morse and returning a timeline that still
points at the Morse symbols. The WebSocket server decides when to start a
session and how to emit events; this module decides what audio buffer and
symbol schedule the learner hears.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from copy_653.audio import synth, timing
from copy_653.audio.parameters import AudioParameters
from copy_653.letters import NATO_PHONETIC_NAMES, find_anchors_dir, load_wav

TimelineRow = tuple[str, float, float, int, str]

INSTRUCTION_SYMBOLS: frozenset[str] = frozenset({"K", "M", "U"})


def find_instruction_dir() -> Path:
    """Locate ``assets/audio/instruction`` by walking up from this file."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "assets" / "audio" / "instruction"
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        f"Could not locate assets/audio/instruction relative to {here}. "
        "v0 expects an editable install layout (spec §11.1)."
    )


def build_word_detection_audio(
    words: list[str],
    focus_symbols: tuple[str, ...],
    audio_params: AudioParameters,
) -> tuple[np.ndarray, list[TimelineRow]]:
    """Render Word Detection audio and the word-aware Morse timeline.

    Spoken prompts are intentionally limited to the early Koch focus symbols
    with shipped instruction recordings: K, M, and U. Words without those focus
    symbols keep the original Morse-only rendering.
    """
    focus_instruction_symbols = INSTRUCTION_SYMBOLS & set(focus_symbols)
    has_instructions = any(set(word.upper()) & focus_instruction_symbols for word in words)
    if not has_instructions:
        return synth.synthesize_words(words, audio_params), synth.compute_word_timeline(
            words, audio_params
        )

    anchors_dir = find_anchors_dir()
    instruction_dir = find_instruction_dir()
    wav_cache: dict[Path, np.ndarray] = {}

    inter_char = synth.synthesize_silence(
        timing.inter_character_seconds(audio_params), audio_params
    )
    inter_word = synth.synthesize_silence(timing.inter_word_seconds(audio_params), audio_params)

    parts: list[np.ndarray] = []
    timeline: list[TimelineRow] = []
    cursor = 0.0
    sample_rate = audio_params.sample_rate_hz

    for word_index, word in enumerate(words, start=1):
        if word_index > 1:
            parts.append(inter_word)
            cursor += len(inter_word) / sample_rate

        instruction = _instruction_samples(
            word,
            focus_instruction_symbols,
            audio_params,
            anchors_dir,
            instruction_dir,
            wav_cache,
        )
        if len(instruction):
            parts.append(instruction)
            cursor += len(instruction) / sample_rate

        normalized_word = word.lower()
        for symbol_index, symbol in enumerate(word.upper()):
            if symbol_index > 0:
                parts.append(inter_char)
                cursor += len(inter_char) / sample_rate

            symbol_samples = synth.synthesize_symbol(symbol, audio_params)
            t_on = cursor
            cursor += len(symbol_samples) / sample_rate
            timeline.append((symbol, t_on, cursor, word_index, normalized_word))
            parts.append(symbol_samples)

    samples = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    return samples.astype(np.float32, copy=False), timeline


def instruction_symbols_for_word(
    word: str, focus_instruction_symbols: frozenset[str]
) -> tuple[str, ...]:
    """Return unique focus symbols in word order that should be spoken."""
    symbols: list[str] = []
    seen: set[str] = set()
    for symbol in word.upper():
        if symbol in focus_instruction_symbols and symbol not in seen:
            symbols.append(symbol)
            seen.add(symbol)
    return tuple(symbols)


def _instruction_samples(
    word: str,
    focus_instruction_symbols: frozenset[str],
    audio_params: AudioParameters,
    anchors_dir: Path,
    instruction_dir: Path,
    wav_cache: dict[Path, np.ndarray],
) -> np.ndarray:
    symbols = instruction_symbols_for_word(word, focus_instruction_symbols)
    if not symbols:
        return np.zeros(0, dtype=np.float32)

    parts = [_load_wav_at_session_rate(instruction_dir / "listen-for.wav", audio_params, wav_cache)]
    for index, symbol in enumerate(symbols):
        if index > 0:
            parts.append(
                _load_wav_at_session_rate(instruction_dir / "and.wav", audio_params, wav_cache)
            )
        parts.append(
            _load_wav_at_session_rate(
                anchors_dir / f"{NATO_PHONETIC_NAMES[symbol]}.wav",
                audio_params,
                wav_cache,
            )
        )
    return np.concatenate(parts).astype(np.float32, copy=False)


def _load_wav_at_session_rate(
    path: Path,
    audio_params: AudioParameters,
    wav_cache: dict[Path, np.ndarray],
) -> np.ndarray:
    cached = wav_cache.get(path)
    if cached is not None:
        return cached

    samples, sample_rate = load_wav(path)
    if sample_rate != audio_params.sample_rate_hz:
        samples = _resample_linear(samples, sample_rate, audio_params.sample_rate_hz)

    wav_cache[path] = samples
    return samples


def _resample_linear(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if len(samples) == 0 or source_rate == target_rate:
        return samples.astype(np.float32, copy=False)

    duration = len(samples) / source_rate
    target_len = int(round(duration * target_rate))
    if target_len <= 0:
        return np.zeros(0, dtype=np.float32)

    source_times = np.arange(len(samples), dtype=np.float64) / source_rate
    target_times = np.arange(target_len, dtype=np.float64) / target_rate
    return np.interp(target_times, source_times, samples).astype(np.float32)
