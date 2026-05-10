"""Letter listening sequence: phonetic anchor + morse, paired and bare.

The learner clicks a letter on the Letters page; the engine plays a
fixed shape:

    [wav] gap [morse] gap   x phonetic_pairs    (default 3)
    [morse] gap             x bare_repeats      (default 3)

Three paired anchors give the ear a name to hang the morse on, then
bare morse repeats so the spoken anchor stops being needed. The whole
thing is one calm uninterrupted listening block — the user does not
have to interact again until they want a different letter.

This module is the orchestrator. It is async but the heavy lifting
(audio playback) blocks; we drop into a thread for each segment via
:func:`asyncio.to_thread` so the event loop stays responsive enough
to honour cancellation between segments. Mid-segment cancellation is
not pursued in v0: every segment is short (~1 s), so waiting for one
to finish before honouring a new click is acceptable behaviour.

Per spec §1.5 failures surface plainly. Missing wav, unknown letter,
audio device unavailable — all propagate as exceptions rather than
becoming silent no-ops.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from copy_653.audio import synth
from copy_653.audio.parameters import AudioParameters
from copy_653.letters.wav import load_wav

# NATO phonetic alphabet, ITU/ICAO. Maps each letter to the spoken
# anchor name used as a wav filename. Lowercase to match the
# on-disk recordings.
NATO_PHONETIC_NAMES: dict[str, str] = {
    "A": "alpha", "B": "bravo", "C": "charlie", "D": "delta",
    "E": "echo", "F": "foxtrot", "G": "golf", "H": "hotel",
    "I": "india", "J": "juliet", "K": "kilo", "L": "lima",
    "M": "mike", "N": "november", "O": "oscar", "P": "papa",
    "Q": "quebec", "R": "romeo", "S": "sierra", "T": "tango",
    "U": "uniform", "V": "victor", "W": "whiskey", "X": "xray",
    "Y": "yankee", "Z": "zulu",
}  # fmt: skip

# Spoken numeral names. Files live in assets/audio/numerals_spoken/
# as {digit}.wav (e.g. 0.wav, 1.wav ... 9.wav).
NUMERAL_NAMES: dict[str, str] = {
    "0": "0", "1": "1", "2": "2", "3": "3", "4": "4",
    "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
}  # fmt: skip

DIGITS: frozenset[str] = frozenset(NUMERAL_NAMES)


@dataclass(frozen=True, slots=True)
class LettersConfig:
    """Pacing knobs for the letter listening sequence.

    Defaults are tuned for unhurried listening: ~600 ms between the
    spoken anchor and its morse so the ear has time to anticipate the
    pairing, ~1 s between pairs so each pair feels like its own unit,
    and ~800 ms between bare morse repeats once the anchor is gone so
    the ear can settle without rushing.

    Attributes
    ----------
    phonetic_pairs:
        How many ``[wav, morse]`` pairs to play before the bare
        repeats begin. Spec §2.6 calls for paired anchors; three
        pairs is enough to anchor most letters without becoming
        rote.
    bare_repeats:
        How many bare morse repeats follow the paired anchors. The
        anchor is the *training wheel*; once it has done its job the
        ear gets clean morse to lock in.
    gap_within_pair_seconds:
        Silence between the spoken anchor and the morse that follows
        it inside a pair.
    gap_between_pairs_seconds:
        Silence between one pair's morse and the next pair's anchor.
        Slightly longer than the within-pair gap so the unit boundary
        is audible.
    gap_between_bare_seconds:
        Silence between bare morse repeats.
    """

    phonetic_pairs: int = 3
    bare_repeats: int = 3
    gap_within_pair_seconds: float = 0.6
    gap_between_pairs_seconds: float = 1.0
    gap_between_bare_seconds: float = 0.8

    def __post_init__(self) -> None:
        if self.phonetic_pairs < 0:
            raise ValueError(f"phonetic_pairs must be non-negative, got {self.phonetic_pairs}")
        if self.bare_repeats < 0:
            raise ValueError(f"bare_repeats must be non-negative, got {self.bare_repeats}")
        if self.phonetic_pairs == 0 and self.bare_repeats == 0:
            raise ValueError(
                "at least one of phonetic_pairs or bare_repeats must be positive — "
                "an empty sequence would play nothing"
            )
        for name, value in (
            ("gap_within_pair_seconds", self.gap_within_pair_seconds),
            ("gap_between_pairs_seconds", self.gap_between_pairs_seconds),
            ("gap_between_bare_seconds", self.gap_between_bare_seconds),
        ):
            if value < 0:
                raise ValueError(f"{name} must be non-negative, got {value}")


def find_anchors_dir() -> Path:
    """Locate ``assets/audio/nato_phonetic`` by walking up from this file.

    Mirrors :func:`copy_653.server.app.find_web_root` — works for the
    editable install layout that v0 uses (spec §11.1). A future
    packaged install would need ``importlib.resources``; not v0.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "assets" / "audio" / "nato_phonetic"
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        f"Could not locate assets/audio/nato_phonetic relative to {here}. "
        "v0 expects an editable install layout (spec §11.1)."
    )


def find_numerals_dir() -> Path:
    """Locate ``assets/audio/numerals_spoken`` by walking up from this file."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "assets" / "audio" / "numerals_spoken"
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        f"Could not locate assets/audio/numerals_spoken relative to {here}. "
        "v0 expects an editable install layout (spec §11.1)."
    )


def wav_path_for(
    symbol: str,
    anchors_dir: Path,
    numerals_dir: Path | None = None,
) -> Path:
    """Resolve the wav file for ``symbol``.

    Letters are resolved under ``anchors_dir`` (nato_phonetic/).
    Digits are resolved under ``numerals_dir`` (numerals_spoken/);
    if ``numerals_dir`` is not supplied, :func:`find_numerals_dir`
    is called automatically.

    Raises :class:`KeyError` if the symbol has no anchor defined.
    """
    upper = symbol.upper()
    if upper in NATO_PHONETIC_NAMES:
        return anchors_dir / f"{NATO_PHONETIC_NAMES[upper]}.wav"
    if upper in DIGITS:
        ndir = numerals_dir if numerals_dir is not None else find_numerals_dir()
        return ndir / f"{upper}.wav"
    raise KeyError(upper)


async def play_letter_sequence(
    symbol: str,
    audio_params: AudioParameters,
    letters_config: LettersConfig,
    anchors_dir: Path,
    *,
    play_fn=None,
    sleep_fn=None,
) -> None:
    """Play the wav+morse listening sequence for a single letter.

    Loads the phonetic anchor wav once, synthesises the morse once,
    then plays the configured number of pairs followed by bare
    repeats. Each playback runs in a worker thread; gaps are
    :func:`asyncio.sleep` so cancellation can take effect between
    segments.

    Parameters
    ----------
    symbol:
        Single-letter symbol (case-insensitive). ``KeyError`` is
        raised for symbols with no NATO anchor defined.
    audio_params:
        Audio parameters used to synthesise the morse and to pin the
        sounddevice output device.
    letters_config:
        Pacing for the sequence (number of pairs, gaps).
    anchors_dir:
        Directory holding the NATO wav files (one per letter).
    play_fn:
        Override for the playback primitive — used by tests to
        observe call order without touching PortAudio. Signature:
        ``play_fn(samples: np.ndarray, sample_rate_hz: int,
        output_device: int | str | None) -> None``. Defaults to
        :func:`_play_samples`.
    sleep_fn:
        Override for the gap primitive — used by tests to observe
        gap durations. Signature: ``sleep_fn(seconds: float) ->
        Awaitable[None]``. Defaults to :func:`asyncio.sleep`.
    """
    if play_fn is None:
        play_fn = _play_samples
    if sleep_fn is None:
        sleep_fn = asyncio.sleep

    upper = symbol.upper()
    wav_path = wav_path_for(upper, anchors_dir)

    wav_samples, wav_rate = load_wav(wav_path)
    morse_samples = synth.synthesize_sequence([upper], audio_params)
    morse_rate = audio_params.sample_rate_hz
    output_device = audio_params.output_device

    # Phonetic pairs: wav, gap, morse, gap_between_pairs (last pair's
    # trailing gap doubles as the lead-in to the bare repeats).
    for i in range(letters_config.phonetic_pairs):
        await asyncio.to_thread(play_fn, wav_samples, wav_rate, output_device)
        await sleep_fn(letters_config.gap_within_pair_seconds)
        await asyncio.to_thread(play_fn, morse_samples, morse_rate, output_device)
        # Gap after every pair — including the last pair, so the
        # transition into the bare repeats has the same shape as the
        # pair-to-pair transition. A bare-repeats-only sequence skips
        # this entirely.
        if i < letters_config.phonetic_pairs - 1 or letters_config.bare_repeats > 0:
            await sleep_fn(letters_config.gap_between_pairs_seconds)

    # Bare morse repeats. Gap between, no trailing silence after the
    # last repeat — the sequence ends when the last morse decays.
    for i in range(letters_config.bare_repeats):
        await asyncio.to_thread(play_fn, morse_samples, morse_rate, output_device)
        if i < letters_config.bare_repeats - 1:
            await sleep_fn(letters_config.gap_between_bare_seconds)


def _play_samples(
    samples: np.ndarray,
    sample_rate_hz: int,
    output_device: int | str | None,
) -> None:
    """Blocking playback primitive for a single sample buffer.

    Mirrors :func:`copy_653.audio.playback.play` but takes an explicit
    sample rate so the wav (recorded rate) and the morse (synth rate)
    can both be played without coercing one to the other. ``sounddevice``
    happily streams either at its native rate.
    """
    # Lazy import — see playback.py for the rationale (PortAudio is
    # optional at module import time; only required when audio is
    # actually requested).
    import sounddevice as sd

    sd.play(
        samples,
        samplerate=sample_rate_hz,
        device=output_device,
        blocking=True,
    )
