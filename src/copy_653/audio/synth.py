"""Sine-wave synthesis with raised-cosine envelope.

The engine produces audio by:

1. Generating a sine wave at the configured tone frequency for the
   duration of an element (dit or dah).
2. Applying a raised-cosine envelope to the start and end of each
   element to suppress keyclicks (sharp on/off generates broadband
   artefacts that a real receiver would reveal as harshness).
3. Concatenating elements and silences according to the symbol's CW
   pattern and the :class:`AudioParameters`.

All functions in this module are pure: they return numpy arrays and
have no side effects. Playback (which has side effects) lives in
:mod:`copy_653.audio.playback`.
"""

from __future__ import annotations

import numpy as np

from copy_653.audio import patterns, timing
from copy_653.audio.parameters import AudioParameters


def generate_tone(duration_seconds: float, params: AudioParameters) -> np.ndarray:
    """Generate a sine-wave tone of the given duration.

    Returns a 1-D float32 numpy array, suitable to write directly to a
    PortAudio stream. The peak amplitude is ``params.amplitude``,
    defaulted well below digital full scale for hearing safety
    (see spec §2.7).
    """
    n_samples = int(round(duration_seconds * params.sample_rate_hz))
    # float32 throughout — matches what sounddevice expects by default
    # and halves the memory footprint vs float64.
    t = np.arange(n_samples, dtype=np.float32) / np.float32(params.sample_rate_hz)
    sine = np.sin(2 * np.pi * params.tone_frequency_hz * t)
    # Apply amplitude as a final scalar multiply. AudioParameters
    # validates 0 < amplitude <= 1 so we cannot silently clip here.
    return (sine * params.amplitude).astype(np.float32)


def apply_envelope(samples: np.ndarray, params: AudioParameters) -> np.ndarray:
    """Apply a raised-cosine envelope to the start and end of ``samples``.

    The envelope ramps from 0 → 1 over the first ``ramp_samples`` and
    1 → 0 over the last ``ramp_samples``. The middle of the buffer is
    untouched.

    If the buffer is shorter than 2 × ramp_samples (e.g. a very short
    dit at very fast WPM), the head and tail ramps overlap; the
    minimum of the two ramps is used in the overlap region, producing
    a softer-edged but never keyclick-y tone.

    Returns a new array; the input is not modified.
    """
    ramp_samples = int(round(params.envelope_ramp_seconds * params.sample_rate_hz))
    if ramp_samples == 0:
        return samples.copy()

    # Raised-cosine ramp: 0 → 1 smoothly via 0.5 * (1 - cos(πt)).
    # Compared to a linear ramp this has zero-derivative endpoints,
    # so the spectral skirt is much cleaner.
    ramp = 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, ramp_samples, dtype=np.float32)))

    envelope = np.ones_like(samples)
    n = len(samples)
    head = min(ramp_samples, n)
    tail = min(ramp_samples, n)
    envelope[:head] = ramp[:head]
    # Apply tail ramp — for short buffers where head and tail overlap,
    # take the minimum so the envelope is always ≤ both ramps.
    envelope[n - tail :] = np.minimum(envelope[n - tail :], ramp[:tail][::-1])
    return samples * envelope


def synthesize_element(is_dah: bool, params: AudioParameters) -> np.ndarray:
    """Render a single dit or dah as audio (tone + envelope)."""
    if is_dah:
        duration = timing.dah_seconds(params.character_speed_wpm)
    else:
        duration = timing.dit_seconds(params.character_speed_wpm)
    tone = generate_tone(duration, params)
    return apply_envelope(tone, params)


def synthesize_silence(duration_seconds: float, params: AudioParameters) -> np.ndarray:
    """Render silence (zero samples) of the given duration."""
    n_samples = int(round(duration_seconds * params.sample_rate_hz))
    return np.zeros(n_samples, dtype=np.float32)


def synthesize_symbol(symbol: str, params: AudioParameters) -> np.ndarray:
    """Render a single symbol (e.g. 'K') as audio.

    The result is the tone elements separated by 1-dit inter-element
    silences. Inter-character spacing is *not* included — see
    :func:`synthesize_sequence` for that.
    """
    pattern = patterns.pattern_for(symbol)
    inter_element = synthesize_silence(
        timing.inter_element_seconds(params.character_speed_wpm), params
    )

    parts: list[np.ndarray] = []
    for i, mark in enumerate(pattern):
        if i > 0:
            parts.append(inter_element)
        parts.append(synthesize_element(mark == "-", params))
    return np.concatenate(parts)


def synthesize_sequence(symbols: list[str], params: AudioParameters) -> np.ndarray:
    """Render a sequence of symbols with inter-character spacing.

    ``symbols`` is a list of single-character strings. v0 does not
    handle word boundaries (no space-separated input); a future
    revision will accept ' ' to mean inter-word spacing.
    """
    if not symbols:
        return np.zeros(0, dtype=np.float32)

    inter_char = synthesize_silence(timing.inter_character_seconds(params), params)

    parts: list[np.ndarray] = []
    for i, symbol in enumerate(symbols):
        if i > 0:
            parts.append(inter_char)
        parts.append(synthesize_symbol(symbol, params))
    return np.concatenate(parts)


def symbol_duration_seconds(symbol: str, params: AudioParameters) -> float:
    """Duration of a single symbol's audio (elements + intra-character gaps).

    Excludes any inter-character spacing — that is the responsibility of
    whatever assembles the sequence.
    """
    pattern = patterns.pattern_for(symbol)
    dit = timing.dit_seconds(params.character_speed_wpm)
    dah = timing.dah_seconds(params.character_speed_wpm)
    inter_element = timing.inter_element_seconds(params.character_speed_wpm)
    elements = sum(dah if mark == "-" else dit for mark in pattern)
    spaces = (len(pattern) - 1) * inter_element
    return elements + spaces


def compute_timeline(symbols: list[str], params: AudioParameters) -> list[tuple[str, float, float]]:
    """For each symbol in the sequence: ``(symbol, t_on, t_off)`` in seconds.

    ``t_on`` and ``t_off`` are relative to the start of the sequence
    (zero at the first symbol's leading edge). The values match the
    schedule produced by :func:`synthesize_sequence`, so a UI consuming
    these timestamps can align display with what is being heard.

    The honesty contract (spec §1.5, §5.3) extends here: these are the
    intended boundaries, derived from the same timing math the synth
    uses, not separately measured.
    """
    if not symbols:
        return []

    inter_char = timing.inter_character_seconds(params)
    out: list[tuple[str, float, float]] = []
    cursor = 0.0
    for i, symbol in enumerate(symbols):
        if i > 0:
            cursor += inter_char
        duration = symbol_duration_seconds(symbol, params)
        out.append((symbol, cursor, cursor + duration))
        cursor += duration
    return out
