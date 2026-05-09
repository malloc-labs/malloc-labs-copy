"""Audio parameters — character speed, effective speed, tone, envelope.

Holds the configurable parameters that govern how Copy synthesises CW
audio. See docs/specification.md §2 for the rationale behind the
defaults and §2.4 for why character speed lives in a narrow useful
band rather than acting as a difficulty knob.
"""

from __future__ import annotations

from dataclasses import dataclass


# Defaults pulled from docs/specification.md §2.2.
#
# 20 WPM character speed sits comfortably above the ~18 WPM "counting
# threshold" — below that the brain has time to consciously decode
# dits and dahs character-by-character, which trains the wrong skill.
DEFAULT_CHARACTER_SPEED_WPM = 20

# 10 WPM effective speed gives wide Farnsworth spacing between
# characters: thinking time *between* shapes without contaminating
# the shapes themselves.
DEFAULT_EFFECTIVE_SPEED_WPM = 10

# 600 Hz is the de-facto standard CW sidetone frequency.
DEFAULT_TONE_FREQUENCY_HZ = 600

# 48 kHz is the common sample rate for modern audio interfaces;
# minimal resampling friction with most systems.
DEFAULT_SAMPLE_RATE_HZ = 48_000

# Raised-cosine envelope ramp time. Sharp on/off transitions on a sine
# wave generate broadband artefacts ("keyclicks") that a real receiver
# would reveal as obvious harshness; a small ramp eliminates them
# without softening rhythm noticeably. 5 ms is the conventional value
# used by most modern CW transmitters.
DEFAULT_ENVELOPE_RAMP_SECONDS = 0.005


@dataclass(frozen=True, slots=True)
class AudioParameters:
    """All knobs that shape how a CW symbol is rendered to audio.

    Frozen so a session can hold one instance and pass it around without
    fearing in-flight mutation. ``slots=True`` keeps the footprint
    small.

    Attributes
    ----------
    character_speed_wpm:
        Speed of the dits and dahs themselves (Words Per Minute, where
        PARIS = 50 dit-units = 1 word). Should sit in the narrow useful
        band of ~18-25 WPM (see spec §2.4).
    effective_speed_wpm:
        Overall WPM after Farnsworth spacing is applied. Must be less
        than or equal to ``character_speed_wpm``; if equal, Farnsworth
        is effectively disabled (standard inter-character spacing
        applies).
    tone_frequency_hz:
        The sidetone frequency in Hz.
    sample_rate_hz:
        Audio sample rate. The synth and playback path must agree on
        this; mismatched rates produce pitch-shifted output.
    envelope_ramp_seconds:
        Duration of the raised-cosine ramp applied to the start and end
        of each tone. Eliminates keyclicks without softening rhythm.
    """

    character_speed_wpm: int = DEFAULT_CHARACTER_SPEED_WPM
    effective_speed_wpm: int = DEFAULT_EFFECTIVE_SPEED_WPM
    tone_frequency_hz: int = DEFAULT_TONE_FREQUENCY_HZ
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    envelope_ramp_seconds: float = DEFAULT_ENVELOPE_RAMP_SECONDS

    def __post_init__(self) -> None:
        # Validation lives at the boundary — these are the combinations
        # most likely to silently produce confusing behaviour rather
        # than an obvious failure.
        if self.character_speed_wpm <= 0:
            raise ValueError(
                f"character_speed_wpm must be positive, got {self.character_speed_wpm}"
            )
        if self.effective_speed_wpm <= 0:
            raise ValueError(
                f"effective_speed_wpm must be positive, got {self.effective_speed_wpm}"
            )
        if self.effective_speed_wpm > self.character_speed_wpm:
            raise ValueError(
                "effective_speed_wpm cannot exceed character_speed_wpm "
                f"(got effective={self.effective_speed_wpm}, "
                f"character={self.character_speed_wpm})"
            )
        if self.tone_frequency_hz <= 0:
            raise ValueError(
                f"tone_frequency_hz must be positive, got {self.tone_frequency_hz}"
            )
        if self.sample_rate_hz <= 0:
            raise ValueError(
                f"sample_rate_hz must be positive, got {self.sample_rate_hz}"
            )
        if self.envelope_ramp_seconds < 0:
            raise ValueError(
                f"envelope_ramp_seconds must be non-negative, "
                f"got {self.envelope_ramp_seconds}"
            )
