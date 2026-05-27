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

# Tone amplitude as a fraction of digital full scale. 0.3 sits around
# -10 dB FS — quiet enough that a learner running headphones at unity
# system volume is not exposed to a sudden harmful tone. Synth content
# is harsher than music at the same level because it is a sustained
# pure tone with no transient masking. The expectation is that the
# learner adjusts their hardware volume (interface, headphone amp,
# system) up to a comfortable listening level rather than relying on
# Copy to be loud by default. See spec §2.7.
DEFAULT_AMPLITUDE = 0.3

# Signal texture defaults are intentionally conservative but non-zero.
# Envelope ramp controls keying softness; tone_distortion and tone_ripple
# add harmonic roughness and AC-hum character respectively. receiver_bed
# sets the noise floor, and cadence_variation adds micro-timing movement.
DEFAULT_RECEIVER_BED = 2
MIN_RECEIVER_BED = 0
MAX_RECEIVER_BED = 10
DEFAULT_TONE_DISTORTION = 0.0
MIN_TONE_DISTORTION = 0.0
MAX_TONE_DISTORTION = 1.0
DEFAULT_TONE_RIPPLE = 0.0
MIN_TONE_RIPPLE = 0.0
MAX_TONE_RIPPLE = 1.0
DEFAULT_CADENCE_VARIATION = 1
MIN_CADENCE_VARIATION = 0
MAX_CADENCE_VARIATION = 5


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
    amplitude:
        Peak sine amplitude as a fraction of digital full scale, in the
        range (0, 1]. Defaulted well below full scale to protect
        headphone users; the learner is expected to adjust hardware
        volume to a comfortable level rather than relying on Copy to
        be loud. See spec §2.7.
    tone_distortion:
        Odd-harmonic clipping depth, 0.0 (pure sine) to 1.0 (heavily
        clipped, buzzy). At 1.0 the waveform approaches a hard-clipped
        sine rich in 3rd/5th/7th harmonics — the "rough AC" character
        of low RST Tone values.
    tone_ripple:
        Amplitude-modulation depth at ~60 Hz, 0.0 (steady) to 1.0
        (deep AM). Simulates the rectified-AC hum audible on low-T
        signals where the transmitter's power supply filtering is poor.
    receiver_bed:
        Learner-facing 0-10 level for the noise floor under generated
        session audio. The dB mapping is steep enough that S1 produces
        a signal-to-noise ratio that requires effort to copy.
    cadence_variation:
        Learner-facing 0-5 level for tiny deterministic movement in
        inter-character and inter-word spacing.
    output_device:
        Audio output device to play through. ``None`` (the default)
        means the system default output. An integer is treated as a
        sounddevice device index; a string is treated as a substring
        match against device names (e.g. ``"Mac mini Speakers"``).
        Pass-through to ``sounddevice.play(device=...)``. Validation
        of the value happens at play time, not at parameter
        construction (we cannot probe the audio system at import).
    """

    character_speed_wpm: int = DEFAULT_CHARACTER_SPEED_WPM
    effective_speed_wpm: int = DEFAULT_EFFECTIVE_SPEED_WPM
    tone_frequency_hz: int = DEFAULT_TONE_FREQUENCY_HZ
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ
    envelope_ramp_seconds: float = DEFAULT_ENVELOPE_RAMP_SECONDS
    amplitude: float = DEFAULT_AMPLITUDE
    tone_distortion: float = DEFAULT_TONE_DISTORTION
    tone_ripple: float = DEFAULT_TONE_RIPPLE
    receiver_bed: int = DEFAULT_RECEIVER_BED
    cadence_variation: int = DEFAULT_CADENCE_VARIATION
    output_device: int | str | None = None

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
            raise ValueError(f"tone_frequency_hz must be positive, got {self.tone_frequency_hz}")
        if self.sample_rate_hz <= 0:
            raise ValueError(f"sample_rate_hz must be positive, got {self.sample_rate_hz}")
        if self.envelope_ramp_seconds < 0:
            raise ValueError(
                f"envelope_ramp_seconds must be non-negative, " f"got {self.envelope_ramp_seconds}"
            )
        if not (0 < self.amplitude <= 1):
            # Hearing-safety guardrail: silence (0) is not what anyone
            # asks for, and clipping (>1) would distort. The valid range
            # is (0, 1] — the default sits well below 1 by design.
            raise ValueError(f"amplitude must be in (0, 1], got {self.amplitude}")
        if not isinstance(self.tone_distortion, (int, float)) or isinstance(
            self.tone_distortion, bool
        ):
            raise ValueError(
                f"tone_distortion must be a number from {MIN_TONE_DISTORTION} "
                f"to {MAX_TONE_DISTORTION}"
            )
        if not MIN_TONE_DISTORTION <= self.tone_distortion <= MAX_TONE_DISTORTION:
            raise ValueError(
                f"tone_distortion must be from {MIN_TONE_DISTORTION} "
                f"to {MAX_TONE_DISTORTION}, got {self.tone_distortion}"
            )
        if not isinstance(self.tone_ripple, (int, float)) or isinstance(self.tone_ripple, bool):
            raise ValueError(
                f"tone_ripple must be a number from {MIN_TONE_RIPPLE} " f"to {MAX_TONE_RIPPLE}"
            )
        if not MIN_TONE_RIPPLE <= self.tone_ripple <= MAX_TONE_RIPPLE:
            raise ValueError(
                f"tone_ripple must be from {MIN_TONE_RIPPLE} "
                f"to {MAX_TONE_RIPPLE}, got {self.tone_ripple}"
            )
        if not isinstance(self.receiver_bed, int) or isinstance(self.receiver_bed, bool):
            raise ValueError(
                f"receiver_bed must be an integer from {MIN_RECEIVER_BED} " f"to {MAX_RECEIVER_BED}"
            )
        if not MIN_RECEIVER_BED <= self.receiver_bed <= MAX_RECEIVER_BED:
            raise ValueError(
                f"receiver_bed must be an integer from {MIN_RECEIVER_BED} " f"to {MAX_RECEIVER_BED}"
            )
        if not isinstance(self.cadence_variation, int) or isinstance(self.cadence_variation, bool):
            raise ValueError(
                f"cadence_variation must be an integer from {MIN_CADENCE_VARIATION} "
                f"to {MAX_CADENCE_VARIATION}"
            )
        if not MIN_CADENCE_VARIATION <= self.cadence_variation <= MAX_CADENCE_VARIATION:
            raise ValueError(
                f"cadence_variation must be an integer from {MIN_CADENCE_VARIATION} "
                f"to {MAX_CADENCE_VARIATION}"
            )
