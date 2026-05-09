# Copy

A CW (morse code) listening environment. Audio-first, deferred verification, structurally absent mentor. The notebook is part of the system.

This is the implementation home for **Copy**, part of [Malloc Labs](https://malloc.org.uk).

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

## Tests

```sh
pip install -e ".[dev]"
pytest
```

## Naming

The package is named `copy_653`; the distribution is `copy-653`. See [docs/specification.md](docs/specification.md) §10.1 for the convention.

## License

[GPL-3.0-or-later](LICENSE).
