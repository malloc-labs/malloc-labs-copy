// Copy — Key timing page browser MIDI input pipeline.
//
// Owns the Web MIDI access lifecycle, the raw-event → server-key-event
// translation, the arm/disarm gate, the keyConfig snapshot received
// from the server's key-input-start event, and the "pending note-ons"
// buffers that appendDiagnosticRow joins against on each sent-symbol.
// Also handles the server-emitted key-event / key-input-reset / error
// messages, since they're all part of the same keying I/O pipeline.
//
// Outbound:
//   - sends start-key-input / start-browser-key-input on connect
//   - sends key-note-event on every accepted formed event
// Inbound:
//   - key-input-start: caches keyConfig, configures sidetone, paints
//     timing diagnostic
//   - key-event: forwards to sidetone for browser source, pushes
//     generated-on into the timing buffer
//   - key-input-reset: drops both pending buffers
//   - error: optional clearCopyExercises + status badge update
//
// Cross-module pokes (setStatus, IMI cue refresh, clearCopyExercises)
// land via installMidiInputAccessors so we don't need a back-import
// into the page controller.

import { clearCopyExercises, clearImiCue, refreshImiCue, setLastNoteOffAt } from "./copy-progress.js";
import {
    BROWSER_MIDI_INPUT_MODE,
    appendRawDiagnosticRow,
    queueDiagElement,
    queueDiagEvent,
    recordDiagnostic,
    updateInputDiagnostic,
} from "./diagnostics.js";
import {
    diagInputEl,
    diagLogEl,
    diagTimingEl,
    statusEl,
} from "./dom.js";
import { setKeyConfig as setSidetoneKeyConfig, sidetone, updateAudioDiagnostic } from "./sidetone.js";
import { selectTrinkeyDevice } from "./trinkey-device.js";
import { formatMs, formatRatio, formatTimestamp, kindForNote } from "./utils.js";

const MAX_DIAGNOSTIC_ROWS = 24;

let keyConfig = null;
let midiInputArmed = true;
let browserMidiAccess = null;
let browserMidiInput = null;
let pendingGeneratedOns = [];
let pendingRawOns = [];

let setStatus = () => {};

export function installMidiInputAccessors(accessors) {
    setStatus = accessors.setStatus;
}

export function getKeyConfig() {
    return keyConfig;
}

export function getMidiInputArmed() {
    return midiInputArmed;
}

export function getBrowserMidiInput() {
    return browserMidiInput;
}

export function clearBrowserMidiInput() {
    if (browserMidiInput) {
        browserMidiInput.onmidimessage = null;
        browserMidiInput = null;
    }
}

export function setMidiInputArmed(armed, reason) {
    midiInputArmed = armed;
    if (!armed) {
        sidetone.mute();
    }
    recordDiagnostic("midi-input-arm", { armed, reason });
    queueDiagEvent(armed ? "input armed" : `input disarmed / ${reason}`);
    updateInputDiagnostic();
    updateAudioDiagnostic();
}

function midiMessageToNoteEvent(message) {
    const [status, note, velocity = 0] = message.data;
    const command = status & 0xf0;
    if (command !== 0x80 && command !== 0x90) return null;

    // message.timeStamp is the CoreMIDI/Web MIDI arrival time in the
    // same domain as performance.now() — using it directly preserves
    // hardware timing through any JS dispatch jitter.
    return {
        note,
        pressed: command === 0x90 && velocity !== 0,
        timestamp: message.timeStamp / 1000,
    };
}

function pageAcceptsMidiInput() {
    // Visibility, not focus: a brief click on another app window is
    // not a reason to drop input. The visibilitychange handler covers
    // genuine off-screen states (tab switched away, window minimised).
    return document.visibilityState === "visible";
}

function handleFormedBrowserMidiEvent(socket, event) {
    const kind = kindForNote(event.note, keyConfig);
    if (!kind || !keyConfig) {
        appendRawDiagnosticRow(event, "ignored / unmapped");
        recordDiagnostic("raw-midi", {
            note: event.note,
            pressed: event.pressed,
            action: "ignored / unmapped",
            mode: BROWSER_MIDI_INPUT_MODE,
        });
        return;
    }

    if (!midiInputArmed) {
        appendRawDiagnosticRow(event, "ignored / input disarmed", kind);
        recordDiagnostic("raw-midi", {
            kind,
            note: event.note,
            pressed: event.pressed,
            action: "ignored / input disarmed",
            mode: BROWSER_MIDI_INPUT_MODE,
        });
        if (!event.pressed) {
            sidetone.keyUp(event.note);
        }
        updateAudioDiagnostic();
        return;
    }

    if (!pageAcceptsMidiInput()) {
        appendRawDiagnosticRow(event, "ignored / page hidden", kind);
        recordDiagnostic("raw-midi", {
            kind,
            note: event.note,
            pressed: event.pressed,
            action: "ignored / page hidden",
            mode: BROWSER_MIDI_INPUT_MODE,
        });
        sidetone.keyUp(event.note);
        return;
    }

    // The Trinkey firmware emits already-formed elements (note-on +
    // note-off per dit/dah). Pass them straight through to sidetone
    // and server decoder.
    appendRawDiagnosticRow(event, "accepted / formed pass-through", kind);
    recordDiagnostic("raw-midi", {
        kind,
        note: event.note,
        pressed: event.pressed,
        action: "accepted / formed pass-through",
        mode: BROWSER_MIDI_INPUT_MODE,
    });
    queueDiagEvent(`formed ${kind} ${event.pressed ? "down" : "up"} / note ${event.note}`);

    if (event.pressed) {
        clearImiCue();
        pendingRawOns.push({ kind, note: event.note, timestamp: Number(event.timestamp) });
        sidetone.keyDown(event.note);
    } else {
        sidetone.keyUp(event.note);
        setLastNoteOffAt(performance.now());
        refreshImiCue();
    }
    updateAudioDiagnostic();
    if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ action: "key-note-event", ...event }));
    }
}

function selectMidiInput(inputs) {
    return selectTrinkeyDevice(inputs);
}

export async function startBrowserMidi(socket) {
    if (!navigator.requestMIDIAccess) {
        diagInputEl.textContent = "browser MIDI unavailable";
        socket.send(JSON.stringify({ action: "start-key-input" }));
        return;
    }

    try {
        const access = await navigator.requestMIDIAccess({ sysex: false });
        browserMidiAccess = access;
        access.addEventListener("statechange", (event) => {
            if (event.port?.type === "input" && event.port.state !== "connected") {
                sidetone.mute();
                setMidiInputArmed(false, "midi input changed");
            }
        });
        const input = selectMidiInput(access.inputs);
        if (!input) {
            diagInputEl.textContent = "no browser MIDI input";
            socket.send(JSON.stringify({ action: "start-key-input" }));
            return;
        }

        browserMidiInput = input;
        browserMidiInput.onmidimessage = (message) => {
            if (socket.readyState !== WebSocket.OPEN) return;
            recordDiagnostic("web-midi-message", {
                input_name: input.name || "browser MIDI",
                data: Array.from(message.data),
            });
            const event = midiMessageToNoteEvent(message);
            if (!event) return;
            handleFormedBrowserMidiEvent(socket, event);
        };

        // Send the current performance.now() so the server can
        // calibrate browser timestamps into its time.monotonic()
        // domain. Without this the decoder's flush-time arithmetic
        // would mix clock epochs.
        socket.send(JSON.stringify({
            action: "start-browser-key-input",
            input_name: input.name || "browser MIDI",
            perf_now: performance.now() / 1000,
        }));
    } catch (error) {
        diagInputEl.textContent = "browser MIDI blocked";
        diagInputEl.title = error?.message || "";
        socket.send(JSON.stringify({ action: "start-key-input" }));
    }
}

export function renderKeyInputStart(event) {
    keyConfig = event;
    setSidetoneKeyConfig(event);
    // Fan-out: any page-specific listener needs ditMs to scale the
    // green/amber/red zones consistently with the cadence renderer.
    document.dispatchEvent(new CustomEvent("copy-653:key-input-start", {
        detail: { ditMs: Number(event.dit_ms_expected) || 60 },
    }));
    recordDiagnostic("key-input-start", {
        source: event.source,
        input_name: event.input_name,
        dit_note: event.dit_note,
        dah_note: event.dah_note,
        dit_ms_expected: event.dit_ms_expected,
    });
    setStatus("connected", "key ready");
    statusEl.title = event.input_name ? `input: ${event.input_name}` : "";
    diagInputEl.textContent = event.source === "browser"
        ? `${event.input_name || "browser MIDI"} / browser`
        : event.input_name || "system default";
    updateInputDiagnostic();
    diagTimingEl.textContent = [
        `${event.character_wpm || "—"} WPM`,
        `${event.effective_wpm || "—"} effective`,
        `dit ${formatMs(event.dit_ms_expected)}`,
        `char ${formatMs(event.character_gap_ms)}`,
        `word ${formatMs(event.word_gap_ms)}`,
    ].join(" / ");
    sidetone.configure(event);
    updateAudioDiagnostic();
}

export function appendDiagnosticRow(event) {
    const startedAt = Number(event.started_at);
    const endedAt = Number(event.ended_at);
    const symbolRawOns = pendingRawOns.filter((entry) => (
        entry.timestamp >= startedAt && entry.timestamp <= endedAt
    ));
    pendingRawOns = pendingRawOns.filter((entry) => entry.timestamp > endedAt);
    const symbolGeneratedOns = pendingGeneratedOns.filter((entry) => (
        entry.timestamp >= startedAt && entry.timestamp <= endedAt
    ));
    pendingGeneratedOns = pendingGeneratedOns.filter((entry) => entry.timestamp > endedAt);

    const row = document.createElement("tr");
    const timestampCell = document.createElement("td");
    const rawCell = document.createElement("td");
    const generatedCell = document.createElement("td");
    const symbolCell = document.createElement("td");
    const morseCell = document.createElement("td");

    timestampCell.textContent = formatTimestamp();
    rawCell.textContent = symbolRawOns.length > 0
        ? symbolRawOns.map((entry) => `${entry.kind} ${entry.note}`).join(" ")
        : "—";
    generatedCell.textContent = symbolGeneratedOns.length > 0
        ? symbolGeneratedOns.map((entry) => `${entry.kind} ${entry.note}`).join(" ")
        : "—";
    symbolCell.textContent = event.symbol || "?";
    morseCell.textContent = event.pattern || "—";

    row.append(timestampCell, rawCell, generatedCell, symbolCell, morseCell);
    diagLogEl.prepend(row);

    while (diagLogEl.children.length > MAX_DIAGNOSTIC_ROWS) {
        diagLogEl.lastElementChild.remove();
    }
}

export function renderKeyEvent(event) {
    const state = event.pressed ? "down" : "up";
    queueDiagEvent(`${event.kind} ${state} / note ${event.note}`);
    recordDiagnostic("server-key-event", {
        kind: event.kind,
        note: event.note,
        pressed: event.pressed,
        duration_ms: event.duration_ms,
        ratio_dits: event.ratio_dits,
    });
    sidetone.configure(event);

    if (event.pressed) {
        pendingGeneratedOns.push({
            kind: event.kind,
            note: event.note,
            timestamp: Number(event.timestamp),
        });
    } else {
        if (Number.isFinite(event.duration_ms)) {
            queueDiagElement([
                event.kind,
                formatMs(event.duration_ms),
                formatRatio(event.ratio_dits),
            ].join(" / "));
        }
    }
    if (keyConfig?.source !== "browser") {
        if (event.pressed) {
            sidetone.keyDown(event.note);
        } else {
            sidetone.keyUp(event.note);
        }
    }
    updateAudioDiagnostic();
}

export function renderKeyInputReset(event) {
    pendingGeneratedOns = [];
    pendingRawOns = [];
    queueDiagEvent(`input reset / ${event.reason || "manual"}`);
    recordDiagnostic("key-input-reset", { reason: event.reason || null });
}

export function renderError(event) {
    const reason = event.reason || "error";
    const detail = event.detail ? `: ${event.detail}` : "";
    recordDiagnostic("server-error", { reason, detail: event.detail || null });
    statusEl.title = `${reason}${detail}`;

    if (reason === "no-claimed-symbols") {
        clearCopyExercises();
    }

    if (reason === "key-input-unavailable" || reason === "key-input-failed") {
        setStatus("connecting", "midi unavailable");
    } else if (reason === "key-input-decode-failed") {
        setStatus("connecting", "decode timing error");
    } else {
        setStatus("connecting", reason);
    }
}
