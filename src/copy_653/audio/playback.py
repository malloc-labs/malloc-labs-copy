"""Audio playback via PortAudio (sounddevice).

The engine generates float32 mono samples (see :mod:`synth`); this
module hands them to the OS audio output. The split is intentional:
synthesis is pure and testable, playback has side effects and depends
on a working audio device.

Per spec §1.5, failures here are surfaced plainly. If the audio
device cannot be opened or playback fails, the exception propagates;
we do not silently retry or substitute a no-op.

Implementation note: ``sounddevice`` is imported lazily inside
:func:`play` rather than at module load. The library binds to
PortAudio when first imported, which means an eager import would
cause this whole module to be unloadable on systems without PortAudio
installed — even when no playback is requested. The lazy import lets
:mod:`synth` and the rest of the audio module remain usable for
buffer generation, recording, and tests on any machine, while still
failing honestly when ``play()`` is actually called.
"""

from __future__ import annotations

import numpy as np

from copy_653.audio.parameters import AudioParameters


def play(samples: np.ndarray, params: AudioParameters) -> None:
    """Play a float32 sample buffer through the default audio device.

    Blocks until playback completes. Mono input; sounddevice and the
    OS handle stereo duplication if the output device is stereo.

    Raises whatever ``sounddevice`` raises if PortAudio is not
    installed or no audio device is available — surfaced honestly per
    spec §1.5.
    """
    # Lazy import — see module docstring for the reason.
    import sounddevice as sd

    sd.play(samples, samplerate=params.sample_rate_hz, blocking=True)
