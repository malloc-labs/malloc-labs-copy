# Copy

A CW (morse code) listening environment. Audio-first, deferred verification, structurally absent mentor. The notebook is part of the system.

This is the implementation home for **Copy**, part of [Malloc Labs](https://malloc.org.uk).

> **Hearing safety — read before first play.** Copy synthesises a sustained pure sine tone, which is harsher on the ear than music at the same digital level. The default output amplitude is 0.3 (~-10 dB FS) for this reason. On macOS, per-app routing utilities (SoundSource, BlackHole, etc.) cannot see this audio — sounddevice writes via CoreAudio HAL directly and bypasses the consumer mixing graph those utilities hook. The volume controls that apply: `AudioParameters.amplitude` in your config, your audio interface's hardware level, and (where the device exposes one) the macOS master output. Set hardware levels low before first play, especially with headphones.

## Design

- [docs/philosophy.md](docs/philosophy.md) — design contracts and methodology
- [docs/specification.md](docs/specification.md) — v0 system specification

## Run

System dependency: PortAudio (`sudo apt install libportaudio2` on Debian/Ubuntu, equivalent on other platforms). Required at runtime for audio playback.

```sh
git clone git@github.com:malloc-labs/malloc-labs-copy.git
cd malloc-labs-copy
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m copy_653                  # prints version banner
python -m copy_653.audio.demo K     # synthesises and plays "K"
python -m copy_653.audio.demo KMK   # synthesises and plays a sequence
```

The engine is not yet wired together. Audio synthesis works; session lifecycle, MIDI input, and the UI are still pending.

## Configure

Optional. Without a config file, the audio defaults from the spec apply.

```sh
mkdir -p ~/.local/share/copy_653
cat > ~/.local/share/copy_653/config.toml <<'EOF'
[audio]
character_speed_wpm = 25
tone_frequency_hz = 600
amplitude = 0.3
output_device = "Mac mini Speakers"   # name substring or device index
EOF
```

Any subset of `[audio]` keys is valid; omitted keys take defaults. Unknown keys are silently ignored (forward compatibility). Validation errors surface honestly per spec §1.5.

## Tests

```sh
pip install -e ".[dev]"
pytest
```

## Naming

The package is named `copy_653`; the distribution is `copy-653`. See [docs/specification.md](docs/specification.md) §10.1 for the convention.

## License

[GPL-3.0-or-later](LICENSE).
