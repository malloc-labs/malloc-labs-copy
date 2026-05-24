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

python -m copy_653                       # start the engine on configured/default host:port
python -m copy_653 --port 9000           # override the configured port
python -m copy_653 --port-search-span 50 # widen the bump-up search window
```

For same-machine USB MIDI key input, install the optional MIDI backend in the
environment that runs Copy:

```sh
pip install -e ".[midi]"
```

For hosted/headless use, leave the optional MIDI backend uninstalled and use a
browser with Web MIDI support on the machine that has the key attached. The Key
Timing page reads the local browser MIDI device and sends normalized key events
to the Copy service over the websocket.

The engine starts an HTTP + WebSocket server on `127.0.0.1:8653` by default.
If that port is in use, the engine probes upward by up to 20 ports and prints
the bound URL on stdout (per spec §1.5 — fail loudly, never silently). Press
`Ctrl-C` to stop.

Status: audio synthesis, Koch sequence generation, Symbol Exposure playback, audio timing and signal texture settings, Settings-page test message playback/export, Trinkey MIDI key input with Freeplay, Cadence, and Copy Key pages, locked post-session review, per-record-kind backup/export, and persistent JSON session records (`koch-exercise`, `cadence-send`, `copy-key`) are wired.

## Signal texture

Copy's generated CW is intentionally clean, but not completely sterile. A
perfect sine tone in silence can become tiring over longer listening sessions,
more like a monitor beep than a signal with physical presence. Signal texture
adds a restrained listening condition beneath the normal CW timing: the learner
still hears the configured character speed and Farnsworth spacing, but the tone
has enough shape, floor, and small cadence movement to feel more natural.

| Setting | Default | Range | Mathematical mapping | Intent |
| --- | ---: | ---: | --- | --- |
| Tone Shape | 2 | 0-10 | Maps to raised-cosine envelope ramp seconds: `0 -> 0ms`, `1 -> 3ms`, `2 -> 5ms`, `3 -> 7ms`, `4 -> 8.5ms`, `5 -> 10ms`, then 11-15ms through level 10. | Softens the keying edge without changing the symbol timing contract. |
| Receiver Bed | 2 | 0-10 | Adds deterministic shaped floor at roughly `-50 + (level * 1.5)` dB relative to configured tone amplitude; level 2 is about -47 dB. | Gives the signal quiet acoustic space without turning it into band-condition training. |
| Cadence Variation | 1 | 0-5 | Applies deterministic spacing variation up to `level * 0.6%` around inter-character and inter-word gaps; level 1 is at most +/-0.6%, level 5 is at most +/-3%. | Reduces metronomic sterility while preserving dit/dah identity and configured WPM. |

The Settings page includes a fixed Morse test message for quickly auditioning
those values: `ARE YOU READY`, a two-second phrase gap, `CAN YOU HEAR ME`,
another two-second gap, then `YES LOUD AND CLEAR`. **Play** sends it through the
current audio output; **Save WAV** exports the same generated signal so the
clean and textured versions can be inspected or compared with external tools.

## Browser test

After `python -m copy_653`, open the URL it prints (default `http://127.0.0.1:8653`) in any modern browser. Current browser surfaces include:

- **Guided Listening → Symbol Exposure**: play a single symbol's spoken anchor plus Morse sequence for reference.
- **Koch Method → Exercises**: claim/unclaim symbols, start or stop a random Koch listening session, then expand the locked review to see clock-time symbol entries with spoken Morse patterns.
- **Key → Freeplay**: free-form timing and spacing practice. Displays the known-symbol sequence and decodes formed Trinkey MIDI dit/dah notes into sent symbols.
- **Key → Cadence**: the same decode pipeline plus a Copy section with five sentence-shaped exercises drawn from the claimed set. Digit keys 1-9 select an exercise; correctly keying the active exercise (right symbols *and* right word/character gaps) auto-advances to the next, and finishing the last requests a fresh batch. A collapsible "review rhythm" panel shows per-symbol timing zones for the recently sent stream.
- **Key → Copy Key**: head-copy exercises — listen to audio, hold it, then key it back. Exercises are shorter (1-4 symbols, max 2 words) and scored on the head-copy task itself. Gear 0 applies tighter symbol caps per burden band.
- **Operational** and **Utilities**: placeholder landing pages for future callsign/prosign/noise work and audio/device tooling respectively.
- Diagnostic readouts on the Key pages (raw MIDI log, decoder telemetry) are hidden until Developer Mode is enabled in Settings.
- **Settings**: four tabs — **App** (Words Per Minute, Signal Texture, Key Input incl. Keyer Mode and Sync now, Test Message, Developer), **Koch Exercises** (per-symbol rollup tables, lifetime history dialog, calendar, and backup — drawn from `koch-exercise` records), **Key Exercises** (the same rollup/lifetime/calendar/backup view for `cadence-send` records), and **Copy > Key** (the same for `copy-key` records). The Developer section holds the Developer Mode toggle (reveals diagnostics on the Key pages) and the HH Clear easter egg (keying two H's in a row clears the Sent area). The server persists audio, key-input, and HH-Clear values to the shared config; Developer Mode is local to the browser via `localStorage`.

The WebSocket protocol is documented at the top of [`src/copy_653/server/app.py`](src/copy_653/server/app.py).

## Configure

Optional. Without a config file, the audio defaults from the spec apply.

```sh
mkdir -p ~/.local/share/copy_653
cat > ~/.local/share/copy_653/config.toml <<'EOF'
[audio]
character_speed_wpm = 20      # character rhythm
effective_speed_wpm = 10      # effective speed after Farnsworth spacing
tone_frequency_hz = 600
amplitude = 0.3
receiver_bed = 2
cadence_variation = 1
output_device = "Mac mini Speakers"   # name substring or device index

[server]
host = "127.0.0.1"
port = 8653
port_search_span = 20
EOF
```

Any subset of `[audio]` and `[server]` keys is valid; omitted keys take defaults.
`effective_speed_wpm` must be less than or equal to `character_speed_wpm`; set
them equal to disable Farnsworth spacing. Tone Shape is stored as
`envelope_ramp_seconds` in config; the Settings page maps the 0-10 control to
the ramp values shown above. Unknown keys are silently ignored (forward
compatibility). Validation errors surface honestly per spec §1.5.

The same file also holds several engine-managed or rarely-edited tables:
`[symbols].claimed` (the learner's claimed set, written by the engine on
claim-symbol), `[session].duration_seconds` (default 30s, used by listening
sessions), `[midi.key]` (note numbers, input-name substring, and keyer mode
for the TRRS Trinkey), `[storage].save_directory` (where session records and
backups go), `[developer].hh_clear_enabled`, and `[letters]` (letter
listening sequence pacing knobs). See
[`src/copy_653/config.py`](src/copy_653/config.py) for the exhaustive field
list.

## Tests

```sh
pip install -e ".[dev]"
pytest
```

## Naming

The package is named `copy_653`; the distribution is `copy-653`. See [docs/specification.md](docs/specification.md) §10.1 for the convention.

## License

[GPL-3.0-or-later](LICENSE).
