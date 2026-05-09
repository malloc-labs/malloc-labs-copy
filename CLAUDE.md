# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Copy** (`copy_653`) — a CW (morse code) listening environment. Pre-alpha; the audio synthesis pipeline works but session lifecycle, MIDI input, server, and UI are unimplemented stubs.

The package is `copy_653`; the distribution is `copy-653`. The `_653` suffix is intentional and avoids shadowing stdlib `copy`. When the developer obtains a UK amateur radio licence the package is renamed to `copy_{callsign}`, which is a semver MAJOR boundary (see `docs/specification.md` §10.1).

## Read the design docs before touching anything

This project is contract-driven. **`docs/philosophy.md` and `docs/specification.md` are load-bearing** — before adding or changing behaviour, check both.

The non-goals list in spec §9 is part of the spec, not commentary. Things explicitly excluded that look like obvious "improvements":

- No scoring, grading, percentages, streaks, badges, hit rate, or progression metrics.
- No encouragement copy, hints, congratulations, or simulated mentor.
- No silent retries or fallback behaviour on errors — failures surface plainly (spec §1.5).
- No automatic difficulty adjustment, no notebook OCR/capture, no telemetry.
- No real-time correctness feedback during a listening session.

If a task seems to call for any of these, stop and re-read the spec — it is probably a contract violation regardless of how small the addition seems.

Other contract surfaces worth knowing inline:

- **Hearing safety.** Default `amplitude=0.3` (~-10 dB FS) is deliberate (spec §2.7). Don't raise it without reason; don't add normalisation/limiting/AGC.
- **Honesty contract.** When something fails, raise — don't fall back to a no-op or substitute defaults. `config.py` propagates parse/validation errors on purpose; `playback.play` propagates PortAudio errors on purpose.
- **Listening screen affordance budget: 5.** Hard ceiling, not a guideline (spec §8.3).

## Architecture

Two-process design (spec §1): a headless Python **engine** that owns audio out, MIDI in, sequence generation, timing, and truth recording; and a **UI** that is static HTML/CSS/vanilla JS served by the engine on localhost. The engine never imports the UI; the UI never reaches into engine internals. They communicate via HTTP/WebSocket. This separation is what permits a future Pi-class deployment without architectural change.

`src/copy_653/` is laid out by responsibility — each subpackage has a stub `__init__.py` until built out:

- `audio/` — **the only implemented subsystem.** Pure synthesis (`synth.py`, `timing.py`, `patterns.py`, `parameters.py`) is separated from side-effecting playback (`playback.py`). `demo.py` is the CLI verification path.
- `midi/`, `sequence/`, `server/`, `session/` — empty stubs awaiting implementation.

Important architectural points in the audio module:

- **`AudioParameters` is frozen + slotted** and validated in `__post_init__`. Sessions hold one instance and pass it everywhere. Don't add mutation.
- **Synthesis is pure; playback has side effects.** Keep this split. `playback.play` lazy-imports `sounddevice` so the rest of the audio module is usable on machines without PortAudio (and so tests don't require an audio device).
- **Farnsworth timing** is computed in `timing._space_dit_seconds`. The intra-character element timing always runs at `character_speed_wpm`; only the *space* dit-units are stretched to hit the configured `effective_speed_wpm` (PARIS = 50 dit-units; intra=31, inter-char=12, inter-word=7).
- **CoreAudio HAL caveat (macOS):** sounddevice bypasses the consumer mixing graph, so per-app routing utilities (SoundSource, BlackHole) cannot see Copy's audio. The volume controls that apply are `AudioParameters.amplitude`, the audio interface hardware level, and the OS master output. `output_device` should be pinned in config to remove dependence on default-output state.

## Commands

The conventional venv lives at `/srv/work/malloc-labs/venvs/ml-copy-653/` (host-level convention from spec §10.2). A local `.venv` is also fine.

```sh
# Setup
pip install -e ".[dev]"

# Run (currently just prints the version banner)
python -m copy_653

# Hear synthesised CW (the actual verification path right now)
python -m copy_653.audio.demo K
python -m copy_653.audio.demo KMK
python -m copy_653.audio.demo K --config /tmp/test_config.toml

# Tests
pytest                                          # all
pytest tests/audio/test_timing.py               # one file
pytest tests/audio/test_synth.py::test_name     # one test
pytest -k farnsworth                            # by keyword
```

System dependency for playback: PortAudio (`libportaudio2` on Debian/Ubuntu). Synth + tests work without it; `playback.play` will fail honestly if it isn't installed.

## Config

Audio parameters load from `~/.local/share/copy_653/config.toml` (XDG-style on both Linux and macOS for consistency — see spec §6.3). The file is optional; missing means defaults. Unknown keys in `[audio]` and unknown top-level tables are silently ignored for forward compatibility, but invalid values raise from `AudioParameters.__post_init__`.

## Style

- Python 3.11+. Black + Ruff at line-length 100 (configured in `pyproject.toml`).
- Pre-commit hooks: gitleaks, black, ruff (with `--fix --exit-non-zero-on-fix`), markdownlint, codespell. Install with `pre-commit install`.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`).
- Module docstrings reference back to the spec/philosophy section that motivates them. When adding a module, follow the same convention — it's how the contract stays visible from the code.

## Frontend (when you get to it)

Hand-spun HTML/CSS/vanilla JS. **No build step, no bundler, no framework, no transpilation, no CSS framework.** Self-hosted woff2 fonts. Aligned to the Malloc Rubicon design system: `web/css/core.css` uses `--mr-*` tokens; Copy-specific outliers go in `web/css/copy-653.css` and are graduated back into `core.css` if generally useful. No red. Dark theme default.
