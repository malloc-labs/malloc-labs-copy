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

Status: audio synthesis, Koch sequence generation, Symbol Exposure playback, audio timing and signal texture settings with looping texture preview, Settings-page test message playback/export, Trinkey MIDI key input with Freeplay, Cadence, and Copy Key pages, locked post-session review, per-record-kind backup/export, and persistent JSON session records (`koch-exercise`, `cadence-send`, `copy-key`) are wired.

## Signal texture

Copy's generated CW is intentionally clean, but not completely sterile. A
perfect sine tone in silence can become tiring over longer listening sessions,
more like a monitor beep than a signal with physical presence. Signal texture
adds listening conditions beneath the normal CW timing using the RST (Readability,
Strength, Tone) model from amateur radio: the learner still hears the configured
character speed and Farnsworth spacing, but the signal has realistic floor, tone
quality, and small cadence movement.

| Setting | Default | Range | Mathematical mapping | Intent |
| --- | ---: | ---: | --- | --- |
| Tone Shape (T) | 2 | 0-10 | Drives three mechanisms together: raised-cosine envelope ramp (0-15 ms), harmonic distortion via `tanh` soft-clip (0.0-0.8), and 60 Hz AC-ripple AM (0.0-0.7, engages below level 5). Low values produce the buzzy, hum-modulated character of poorly filtered transmitters. | Shapes the tone quality from clinical sine to rough real-world signal. |
| Receiver Bed (S) | 2 | 0-10 | Adds deterministic shaped floor at `-50 + (level * 4.4)` dB relative to configured tone amplitude, with constant-loudness normalisation (`gain = 1/sqrt(1 + ratio²)`) so total perceived volume stays safe regardless of bed level. At level 2 the floor is about -41 dB; at level 10 the signal-to-noise ratio is ~6 dB. | Gives the signal acoustic space from gentle hiss to genuinely challenging noise floor, without changing headphone volume. |
| Cadence Variation | 1 | 0-5 | Applies deterministic spacing variation up to `level * 0.6%` around inter-character and inter-word gaps; level 1 is at most +/-0.6%, level 5 is at most +/-3%. | Reduces metronomic sterility while preserving dit/dah identity and configured WPM. |

The Settings page exposes S and T as RST 1-9 inputs in the Signal Texture
section. A **Preview** toggle loops random CW from the claimed symbol set through
the current texture settings so the learner can hear changes before saving;
**Save WAV** exports a single preview chunk for external analysis. A separate
fixed Morse test message (**Play** / **Save WAV** in the Test Message section)
sends `ARE YOU READY / CAN YOU HEAR ME / YES LOUD AND CLEAR` through the
current settings.

## Browser test

After `python -m copy_653`, open the URL it prints (default `http://127.0.0.1:8653`) in any modern browser. Current browser surfaces include:

- **Koch Method → Exercises**: claim/unclaim symbols, start or stop a random Koch listening session, then expand the locked review to see clock-time symbol entries with spoken Morse patterns.
- **Key → Freeplay**: free-form timing and spacing practice. Displays the known-symbol sequence and decodes formed Trinkey MIDI dit/dah notes into sent symbols.
- **Key → Cadence**: the same decode pipeline plus a Copy section with five sentence-shaped exercises drawn from the claimed set. Digit keys 1-9 select an exercise; correctly keying the active exercise (right symbols *and* right word/character gaps) auto-advances to the next, and finishing the last requests a fresh batch. A collapsible "review rhythm" panel shows per-symbol timing zones for the recently sent stream.
- **Key → Copy Key**: head-copy exercises — listen to audio, hold it, then key it back. Exercises are shorter (1-4 symbols, max 2 words) and scored on the head-copy task itself. Gear 0 applies tighter symbol caps per burden band.
- Diagnostic readouts on the Key pages (raw MIDI log, decoder telemetry) are hidden until Developer Mode is enabled in Settings.
- **Settings**: three tabs — **App** (Words Per Minute, Signal Texture with Preview/Save WAV, Operator/Fist, Key Input incl. Keyer Mode and Sync now, Test Message, Developer), **Voice** (offline speech recogniser status/configuration/test), and **Exercises** (a quiet link hub for saved-session review pages). Dedicated review pages cover **Koch Exercises** (`koch-exercise` records), **Key Exercises** (`cadence-send` records), **Copy > Key** (`copy-key` records), and **Recognition** records with their rollups, calendars, dialogs, and backup controls. The Developer section holds the Developer Mode toggle (reveals diagnostics on the Key pages) and the HH Clear easter egg (keying two H's in a row clears the Sent area). The server persists audio, key-input, voice, and HH-Clear values to the shared config; Developer Mode is local to the browser via `localStorage`.

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
them equal to disable Farnsworth spacing. Tone Shape is stored as `envelope_ramp_seconds` in config; the Settings page
maps the 0-10 control to the ramp, distortion, and ripple values described
above. `tone_distortion` and `tone_ripple` are derived at load time and not
persisted separately. Unknown keys are silently ignored (forward
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

## Voice input (optional)

Voice is the answer-entry modality for the **Symbol Recognition** page
(spec §2.6). Audio is captured in the browser, streamed as 16-kHz mono
PCM over a WebSocket at `/voice/ws`, and decoded by an offline
[Vosk](https://alphacephei.com/vosk/) recogniser whose grammar is
restricted to the NATO phonetic words, English digit words, and the
prosign phrases the Koch curriculum uses (`.` `,` `?` `/` `=`). Any
off-vocabulary speech collapses to `[unk]` server-side.

The recogniser **faithfully transcribes whatever was uttered** — it does
not filter to the claimed-symbol set. If the learner says "zulu" during
a session where Z isn't claimed, the record shows it. That's the spec
§9 honesty contract: failures (operator-side or recogniser-side)
surface plainly so post-session analysis can tell them apart.

### Install

```sh
pip install -e ".[voice]"

mkdir -p ~/.local/share/copy_653/models
curl -L -o /tmp/vosk-model.zip \
  https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip /tmp/vosk-model.zip -d ~/.local/share/copy_653/models/
```

Then tell the engine where the model lives:

```toml
[voice]
language = "en"
model_path = "vosk-model-small-en-us-0.15"
```

`model_path` resolves against `~/.local/share/copy_653/models/` when
relative; absolute paths are honoured as given.

### Where it shows up

- **Settings → Voice** tab: status grid (language, resolved model path,
  whether the model and `vosk` are installed, overall ready boolean),
  the merged lexicon as a flat reference table, the per-category raw
  JSON files under `<details>`, and a **Recogniser test** dialog that
  opens a real `/voice/ws` and shows live partial/final/symbol output
  alongside a peak level meter. Editable language + model_path inputs
  write the `[voice]` table back through the engine.
- **Koch Method → Symbol Recognition**: when `/api/voice/status` reports
  `ready: true`, the Start button arms voice alongside the listening
  session. As the engine plays each exercise the active answer row
  highlights and accumulates the symbols Vosk hears. After session-end
  the rows unlock for correction and Save persists answers — plus the
  per-exercise `voice_capture` list (`{t, text, symbols}` per Vosk
  final) — into the JSON record. The Truth panel interleaves engine
  symbols and Vosk events on a shared timestamp column so the "two
  recognitions" comparison is visible at a glance.

If `[voice]` is absent or the model directory is missing, the
Recognition page disables Start with an inline notice naming exactly
what's wrong; the rest of Copy is unaffected.

## Tests

```sh
pip install -e ".[dev]"
pytest
```

## Naming

The package is named `copy_653`; the distribution is `copy-653`. See [docs/specification.md](docs/specification.md) §10.1 for the convention.

## License

[GPL-3.0-or-later](LICENSE).
