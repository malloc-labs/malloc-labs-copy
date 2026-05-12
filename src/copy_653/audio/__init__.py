"""Tone synth, envelope, playback.

The audio module is the engine's voice. It is split into:

- :mod:`parameters` — :class:`AudioParameters`, the configuration object.
- :mod:`timing` — WPM ↔ second conversions, including Farnsworth.
- :mod:`patterns` — CW (Morse) symbol patterns.
- :mod:`synth` — pure sine + envelope synthesis (no I/O, testable).
- :mod:`texture` — restrained signal presence helpers.
- :mod:`playback` — sounddevice integration (side effects).

The split between synth and playback is deliberate: synthesis is
reproducible and unit-testable, playback depends on a working audio
device. Per spec §1.5, playback failures surface plainly and are not
silently retried.
"""

from copy_653.audio.parameters import AudioParameters

__all__ = ["AudioParameters"]
