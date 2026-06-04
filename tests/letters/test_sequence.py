"""Tests for the letter listening sequence orchestration.

These exercise call ordering and pacing without touching PortAudio:
``play_letter_sequence`` accepts injected ``play_fn`` and ``sleep_fn``
so the test can record what the engine intended to play.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from copy_653.audio.parameters import AudioParameters
from copy_653.letters import LettersConfig, play_letter_sequence, play_morse_sequence
from copy_653.letters.sequence import wav_path_for

REPO_ROOT = Path(__file__).resolve().parents[2]
ANCHORS_DIR = REPO_ROOT / "assets" / "audio" / "nato_phonetic"


class _Recorder:
    """Records play and sleep calls in order with their arguments."""

    def __init__(self) -> None:
        self.events: list[tuple[str, ...]] = []

    def play(self, samples: np.ndarray, sample_rate_hz: int, output_device) -> None:
        # Record kind (wav vs morse) by sample count rather than identity:
        # the wav buffer is large (~60k samples for ~1.3s @ 48kHz); the
        # morse buffer for a single letter is far smaller.
        kind = "morse" if samples.size < 30_000 else "wav"
        self.events.append(("play", kind, sample_rate_hz, samples.size))

    async def sleep(self, seconds: float) -> None:
        self.events.append(("sleep", seconds))


def _kinds(events) -> list[str]:
    """Return the play kinds (wav/morse) in order."""
    return [e[1] for e in events if e[0] == "play"]


def _gaps(events) -> list[float]:
    """Return the gap durations in order."""
    return [e[1] for e in events if e[0] == "sleep"]


def test_default_sequence_is_three_pairs_then_three_bare():
    """Default LettersConfig: wav,morse x3 then morse x3 = 9 plays total."""
    rec = _Recorder()
    asyncio.run(
        play_letter_sequence(
            "K",
            audio_params=AudioParameters(),
            letters_config=LettersConfig(),
            anchors_dir=ANCHORS_DIR,
            play_fn=rec.play,
            sleep_fn=rec.sleep,
        )
    )

    assert _kinds(rec.events) == [
        "wav",
        "morse",  # pair 1
        "wav",
        "morse",  # pair 2
        "wav",
        "morse",  # pair 3
        "morse",
        "morse",
        "morse",  # bare repeats
    ]


def test_default_pacing_uses_configured_gaps():
    """Gap durations match LettersConfig defaults (0.6 / 1.0 / 0.8)."""
    rec = _Recorder()
    asyncio.run(
        play_letter_sequence(
            "K",
            audio_params=AudioParameters(),
            letters_config=LettersConfig(),
            anchors_dir=ANCHORS_DIR,
            play_fn=rec.play,
            sleep_fn=rec.sleep,
        )
    )

    # Per pair: gap_within_pair (wav→morse) then gap_between_pairs.
    # Last pair's between-pairs gap leads into the bare repeats.
    # Then: gap_between_bare between each bare repeat (n-1 gaps for n).
    assert _gaps(rec.events) == [
        0.6,
        1.0,  # pair 1
        0.6,
        1.0,  # pair 2
        0.6,
        1.0,  # pair 3 → bare
        0.8,
        0.8,  # between three bare repeats
    ]


def test_letter_is_case_insensitive():
    """Lowercase 'k' resolves the same as uppercase 'K'."""
    rec = _Recorder()
    asyncio.run(
        play_letter_sequence(
            "k",
            audio_params=AudioParameters(),
            letters_config=LettersConfig(phonetic_pairs=1, bare_repeats=0),
            anchors_dir=ANCHORS_DIR,
            play_fn=rec.play,
            sleep_fn=rec.sleep,
        )
    )

    # One pair, no bare repeats: wav, gap, morse, no trailing gap.
    assert _kinds(rec.events) == ["wav", "morse"]
    assert _gaps(rec.events) == [0.6]


def test_bare_only_sequence_skips_paired_gap():
    """phonetic_pairs=0 → no wavs and no leading gap."""
    rec = _Recorder()
    asyncio.run(
        play_letter_sequence(
            "K",
            audio_params=AudioParameters(),
            letters_config=LettersConfig(phonetic_pairs=0, bare_repeats=2),
            anchors_dir=ANCHORS_DIR,
            play_fn=rec.play,
            sleep_fn=rec.sleep,
        )
    )

    assert _kinds(rec.events) == ["morse", "morse"]
    assert _gaps(rec.events) == [0.8]


def test_wav_played_at_native_rate_morse_at_synth_rate():
    """Wav plays at its 48 kHz native rate; morse at the AudioParameters rate."""
    rec = _Recorder()
    params = AudioParameters(sample_rate_hz=44_100)
    asyncio.run(
        play_letter_sequence(
            "K",
            audio_params=params,
            letters_config=LettersConfig(phonetic_pairs=1, bare_repeats=1),
            anchors_dir=ANCHORS_DIR,
            play_fn=rec.play,
            sleep_fn=rec.sleep,
        )
    )

    # Find the rates in the order they were played.
    rates = [(e[1], e[2]) for e in rec.events if e[0] == "play"]
    assert rates[0] == ("wav", 48_000)
    assert rates[1] == ("morse", 44_100)
    assert rates[2] == ("morse", 44_100)


def test_morse_preview_assembles_repeats_into_one_lead_in_buffer():
    """Alt-preview opens one audio stream with pre-roll before the first tone."""
    played = []
    params = AudioParameters(
        character_speed_wpm=20,
        effective_speed_wpm=20,
        sample_rate_hz=1_000,
        envelope_ramp_seconds=0.0,
        receiver_bed=0,
        cadence_variation=0,
    )

    asyncio.run(
        play_morse_sequence(
            "E",
            audio_params=params,
            repeats=3,
            gap_seconds=0.2,
            lead_in_seconds=0.2,
            play_fn=lambda samples, sample_rate_hz, output_device: played.append(
                (samples, sample_rate_hz, output_device)
            ),
        )
    )

    assert len(played) == 1
    samples, sample_rate_hz, output_device = played[0]
    # E is one dit: 60 ms at 20 WPM. Total = 200 ms lead-in +
    # 3 × 60 ms tone + 2 × 200 ms gaps.
    assert sample_rate_hz == 1_000
    assert output_device is None
    assert samples.size == 780
    assert np.all(samples[:200] == 0.0)
    assert np.any(samples[200:] != 0.0)


def test_morse_preview_rejects_negative_lead_in():
    with pytest.raises(ValueError, match="lead_in_seconds"):
        asyncio.run(
            play_morse_sequence(
                "E",
                audio_params=AudioParameters(),
                lead_in_seconds=-0.1,
                play_fn=lambda *args: None,
            )
        )


def test_unknown_symbol_raises_keyerror():
    """Symbols with no anchor raise KeyError."""
    with pytest.raises(KeyError):
        asyncio.run(
            play_letter_sequence(
                "@",
                audio_params=AudioParameters(),
                letters_config=LettersConfig(),
                anchors_dir=ANCHORS_DIR,
                play_fn=lambda *a, **k: None,
                sleep_fn=lambda s: asyncio.sleep(0),
            )
        )


NUMERALS_DIR = REPO_ROOT / "assets" / "audio" / "numerals_spoken"
PUNCTUATION_DIR = REPO_ROOT / "assets" / "audio" / "punctuation"


def test_wav_path_resolves_to_lowercase_anchor_filename():
    """K → kilo.wav under the anchors dir."""
    assert wav_path_for("K", ANCHORS_DIR) == ANCHORS_DIR / "kilo.wav"
    assert wav_path_for("z", ANCHORS_DIR) == ANCHORS_DIR / "zulu.wav"


def test_wav_path_resolves_digit_to_numerals_dir():
    """Digits resolve to numerals_spoken/{digit}.wav."""
    assert wav_path_for("5", ANCHORS_DIR, NUMERALS_DIR) == NUMERALS_DIR / "5.wav"
    assert wav_path_for("0", ANCHORS_DIR, NUMERALS_DIR) == NUMERALS_DIR / "0.wav"


def test_wav_path_resolves_punctuation_to_punctuation_dir():
    """Punctuation resolves to punctuation/{name}.wav."""
    assert (
        wav_path_for(".", ANCHORS_DIR, NUMERALS_DIR, PUNCTUATION_DIR)
        == PUNCTUATION_DIR / "full-stop.wav"
    )
    assert (
        wav_path_for("?", ANCHORS_DIR, NUMERALS_DIR, PUNCTUATION_DIR)
        == PUNCTUATION_DIR / "question-mark.wav"
    )
    assert (
        wav_path_for("=", ANCHORS_DIR, NUMERALS_DIR, PUNCTUATION_DIR)
        == PUNCTUATION_DIR / "equalls.wav"
    )


def test_letters_config_rejects_negative_pairs():
    with pytest.raises(ValueError, match="phonetic_pairs"):
        LettersConfig(phonetic_pairs=-1)


def test_letters_config_rejects_all_zero_sequence():
    """An empty sequence (no pairs and no bare repeats) is a config error."""
    with pytest.raises(ValueError, match="empty sequence"):
        LettersConfig(phonetic_pairs=0, bare_repeats=0)


def test_letters_config_rejects_negative_gap():
    with pytest.raises(ValueError, match="gap_within_pair_seconds"):
        LettersConfig(gap_within_pair_seconds=-0.1)
