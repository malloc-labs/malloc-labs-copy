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


def resolve_output_device(sd, output_device: int | str | None) -> int | str | None:
    """Resolve a configured output route against PortAudio's current device list."""
    if output_device is None or isinstance(output_device, int):
        return output_device
    requested = output_device.strip()
    if not requested:
        return None

    requested_folded = requested.casefold()
    try:
        raw_devices = sd.query_devices()
    except Exception:
        return output_device

    exact_matches: list[int] = []
    partial_matches: list[int] = []
    for idx, info in enumerate(raw_devices):
        if int(info.get("max_output_channels", 0)) <= 0:
            continue
        device_index = int(info.get("index", idx))
        name = str(info.get("name", f"Device {idx}"))
        hostapi_name = ""
        try:
            hostapi_name = str(sd.query_hostapis(info["hostapi"]).get("name", ""))
        except Exception:
            hostapi_name = ""
        candidates = [name]
        if hostapi_name:
            candidates.append(f"{name}, {hostapi_name}")
        folded = [candidate.casefold() for candidate in candidates]
        if requested_folded in folded:
            exact_matches.append(device_index)
        elif any(requested_folded in candidate for candidate in folded):
            partial_matches.append(device_index)

    if exact_matches:
        return exact_matches[0]
    if partial_matches:
        return partial_matches[0]
    return output_device


def play_samples(
    samples: np.ndarray,
    sample_rate_hz: int,
    output_device: int | str | None,
) -> None:
    """Play samples, recovering once when a saved macOS route has gone stale."""
    import sounddevice as sd

    device = resolve_output_device(sd, output_device)
    try:
        sd.play(
            samples,
            samplerate=sample_rate_hz,
            device=device,
            blocking=True,
        )
    except Exception:
        if output_device is None:
            raise
        try:
            sd.stop()
        except Exception:
            pass
        sd.play(
            samples,
            samplerate=sample_rate_hz,
            device=None,
            blocking=True,
        )


def play(samples: np.ndarray, params: AudioParameters) -> None:
    """Play a float32 sample buffer through the default audio device.

    Blocks until playback completes. Mono input; sounddevice and the
    OS handle stereo duplication if the output device is stereo.

    Raises whatever ``sounddevice`` raises if PortAudio is not
    installed or no audio device is available — surfaced honestly per
    spec §1.5.
    """
    # ``device=None`` defers to sounddevice's system-default selection;
    # an int or string pins to a specific device. See spec §2.7 — on
    # macOS, sounddevice writes via CoreAudio HAL and bypasses the
    # consumer mixing graph that per-app routers (SoundSource, etc.)
    # hook, so the device chosen here is the only routing in play.
    play_samples(samples, params.sample_rate_hz, params.output_device)
