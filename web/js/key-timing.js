// Copy — Key timing page.
//
// Read-only sequence display for known symbols. The engine pushes the same
// claimed-symbols event used by Koch Exercises; this page only renders it.

import "./developer-mode.js";
import { noteSentSymbol, resetHHClearTracker } from "./hh-clear.js";

const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
const wsUrl = `${wsProtocol}//${location.host}/ws`;

const statusEl = document.querySelector(".status");
const sequenceRow = document.getElementById("sequence-row");
const sentSymbolEl = document.getElementById("sent-symbol");
const sentHistoryEl = document.getElementById("sent-history");
const rhythmReviewToggleEl = document.getElementById("key-rhythm-review-toggle");
const rhythmReviewArrowEl = document.getElementById("key-rhythm-review-arrow");
const rhythmReviewMetaEl = document.getElementById("key-rhythm-review-meta");
const rhythmReviewBodyEl = document.getElementById("key-rhythm-review-body");
const rhythmReviewSymbolsEl = document.getElementById("key-rhythm-review-symbols");
const soundToggleEl = document.getElementById("key-sound-toggle");
const clearSentEl = document.getElementById("key-clear-sent");
const keyInputToggleEl = document.getElementById("key-input-toggle");
const copyDiagnosticsEl = document.getElementById("copy-diagnostics");
const diagInputEl = document.getElementById("diag-input");
const diagAudioEl = document.getElementById("diag-audio");
const diagEventEl = document.getElementById("diag-event");
const diagRawEl = document.getElementById("diag-raw");
const diagElementEl = document.getElementById("diag-element");
const diagGapEl = document.getElementById("diag-gap");
const diagTimingEl = document.getElementById("diag-timing");
const diagLogEl = document.getElementById("diag-log");
const diagRawLogEl = document.getElementById("diag-raw-log");
// Copy section is Cadence-only; absent on the Freeplay page.
const copySymbolEl = document.getElementById("copy-symbol");
const copyHistoryEl = document.getElementById("copy-history");

const MAX_SENT_HISTORY = 48;
const MAX_DIAGNOSTIC_ROWS = 24;
const MAX_RAW_DIAGNOSTIC_ROWS = 32;
const MAX_DIAGNOSTIC_EVENTS = 240;
const DEFAULT_TONE_HZ = 600;
const DEFAULT_AMPLITUDE = 0.3;
const DEFAULT_RAMP_SECONDS = 0.005;
const BROWSER_MIDI_INPUT_MODE = "formed-elements";

let keyConfig = null;
let soundEnabled = false;
let pendingGeneratedOns = [];
let pendingRawOns = [];
let browserMidiAccess = null;
let browserMidiInput = null;
let activeSocket = null;
let diagnosticEvents = [];
let midiInputArmed = true;
let sentReviewEvents = [];
let lastSentEndedAt = null;
let claimedSymbolSet = new Set();
// Left-Alt held state, tracked via event.code so we can scope the
// Cadence preview keybind to LeftAlt only (not RightAlt). Reset on blur
// because the matching keyup may never arrive if focus is lost.
let leftAltDown = false;

// Canonical Koch order — mirrors KOCH_ORDER in patterns.py.
const KOCH_ORDER = [
    "K", "M", "U", "R", "E", "S", "N", "A", "P", "T",
    "L", "W", "I", ".", "J", "Z", "=", "F", "O", "Y",
    ",", "V", "G", "5", "/", "Q", "9", "2", "H", "3",
    "8", "B", "?", "4", "7", "C", "1", "D", "6", "0", "X",
];

function setStatus(state, text) {
    statusEl.dataset.status = state;
    statusEl.textContent = text;
}

function formatMs(value) {
    if (!Number.isFinite(value)) return "—";
    return `${Math.round(value)} ms`;
}

function formatRatio(value) {
    if (!Number.isFinite(value)) return "—";
    return `${value.toFixed(2)} dits`;
}

function formatTimestamp(date = new Date()) {
    const time = date.toLocaleTimeString([], { hour12: false });
    const milliseconds = date.getMilliseconds().toString().padStart(3, "0");
    return `${time}.${milliseconds}`;
}

function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
}

function kindForNote(note) {
    if (note === keyConfig?.dit_note) return "dit";
    if (note === keyConfig?.dah_note) return "dah";
    return null;
}

function recordDiagnostic(type, details = {}) {
    diagnosticEvents.push({
        at: new Date().toISOString(),
        t_ms: Math.round(performance.now()),
        type,
        focus: focusLabel(),
        ...details,
    });

    while (diagnosticEvents.length > MAX_DIAGNOSTIC_EVENTS) {
        diagnosticEvents.shift();
    }
}

function diagnosticText() {
    const header = {
        page: location.href,
        copied_at: new Date().toISOString(),
        user_agent: navigator.userAgent,
        visibility: document.visibilityState,
        focused: document.hasFocus(),
        midi_input_armed: midiInputArmed,
        key_config: keyConfig,
        browser_midi_input_mode: BROWSER_MIDI_INPUT_MODE,
    };
    return [
        JSON.stringify({ type: "diagnostic-header", ...header }),
        ...diagnosticEvents.map((event) => JSON.stringify(event)),
    ].join("\n");
}

function updateInputDiagnostic() {
    keyInputToggleEl.textContent = midiInputArmed ? "input armed" : "arm input";
    const current = diagInputEl.textContent || "";
    if (midiInputArmed && current.includes(" / disarmed")) {
        diagInputEl.textContent = current.replace(" / disarmed", "");
    } else if (!midiInputArmed && !current.includes("disarmed")) {
        diagInputEl.textContent = `${current || "browser MIDI"} / disarmed`;
    }
}

function setMidiInputArmed(armed, reason) {
    midiInputArmed = armed;
    if (!armed) {
        sidetone.mute();
    }
    recordDiagnostic("midi-input-arm", { armed, reason });
    queueDiagEvent(armed ? "input armed" : `input disarmed / ${reason}`);
    updateInputDiagnostic();
    updateAudioDiagnostic();
}

class KeySidetone {
    constructor() {
        this.context = null;
        this.oscillator = null;
        this.gain = null;
        this.activeKeys = new Set();
        this.frequencyHz = DEFAULT_TONE_HZ;
        this.amplitude = DEFAULT_AMPLITUDE;
        this.rampSeconds = DEFAULT_RAMP_SECONDS;
        this.browserBlocked = false;
    }

    configure(event) {
        this.frequencyHz = Number(event.tone_frequency_hz) || this.frequencyHz;
        this.amplitude = clamp(Number(event.amplitude) || this.amplitude, 0, 1);
        this.rampSeconds = Math.max(
            (Number(event.envelope_ramp_ms) || DEFAULT_RAMP_SECONDS * 1000) / 1000,
            0.001,
        );
        if (this.oscillator) {
            this.oscillator.frequency.setValueAtTime(
                this.frequencyHz,
                this.context.currentTime,
            );
        }
        updateAudioDiagnostic();
    }

    ensureStarted() {
        if (this.context) return;

        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) {
            diagAudioEl.textContent = "unsupported";
            return;
        }

        this.context = new AudioContext();
        this.gain = this.context.createGain();
        this.gain.gain.setValueAtTime(0, this.context.currentTime);

        this.oscillator = this.context.createOscillator();
        this.oscillator.type = "sine";
        this.oscillator.frequency.setValueAtTime(this.frequencyHz, this.context.currentTime);
        this.oscillator.connect(this.gain);
        this.gain.connect(this.context.destination);
        this.oscillator.start();
    }

    async unlock() {
        this.ensureStarted();
        if (!this.context) {
            updateAudioDiagnostic();
            return false;
        }
        if (this.context.state === "running") {
            this.browserBlocked = false;
            updateAudioDiagnostic();
            return true;
        }

        try {
            await this.context.resume();
            this.browserBlocked = this.context.state !== "running";
            updateAudioDiagnostic();
            return this.context.state === "running";
        } catch {
            this.browserBlocked = true;
            updateAudioDiagnostic();
            return false;
        }
    }

    keyDown(note) {
        if (!canUseAppSidetone()) return;
        if (!this.context || this.context.state !== "running") {
            this.browserBlocked = true;
            updateAudioDiagnostic();
            return;
        }
        this.activeKeys.add(note);
        this.rampTo(this.amplitude);
    }

    keyUp(note) {
        this.activeKeys.delete(note);
        if (this.activeKeys.size === 0) {
            this.rampTo(0);
        }
    }

    mute() {
        this.activeKeys.clear();
        this.rampTo(0);
    }

    rampTo(value) {
        if (!this.context || !this.gain) return;
        const now = this.context.currentTime;
        this.gain.gain.cancelScheduledValues(now);
        this.gain.gain.setValueAtTime(this.gain.gain.value, now);
        this.gain.gain.linearRampToValueAtTime(value, now + this.rampSeconds);
        updateAudioDiagnostic();
    }

    stateLabel() {
        if (keyConfig?.trinkey_buzzer_enabled) return "trinkey buzzer";
        if (!soundEnabled || !this.context) return "click sound";
        if (this.context.state === "suspended") return "click sound";
        if (this.browserBlocked) return "blocked";
        return this.activeKeys.size > 0 ? "tone" : "ready";
    }
}

const sidetone = new KeySidetone();

function canUseAppSidetone() {
    return soundEnabled && !keyConfig?.trinkey_buzzer_enabled;
}

function updateAudioDiagnostic() {
    diagAudioEl.textContent = sidetone.stateLabel();
    renderSoundToggleLabel();
    soundToggleEl.disabled = Boolean(keyConfig?.trinkey_buzzer_enabled);
}

function renderSoundToggleLabel() {
    if (soundEnabled) {
        soundToggleEl.replaceChildren(makeAccelLabel("m", "ute"));
        soundToggleEl.title = "Mute sidetone (M)";
        soundToggleEl.setAttribute("aria-keyshortcuts", "M");
    } else {
        soundToggleEl.replaceChildren(
            document.createTextNode("enable "),
            makeAccelLabel("s", "ound"),
        );
        soundToggleEl.title = "Enable sidetone (S)";
        soundToggleEl.setAttribute("aria-keyshortcuts", "S");
    }
}

function makeAccelLabel(accel, rest) {
    const u = document.createElement("u");
    u.textContent = accel;
    const fragment = document.createDocumentFragment();
    fragment.append(u, document.createTextNode(rest));
    return fragment;
}

function toggleSidetone() {
    if (soundToggleEl.disabled) return;
    soundToggleEl.click();
}

function renderClearSentLabel() {
    clearSentEl.replaceChildren(makeAccelLabel("c", "lear"));
    clearSentEl.title = "Clear sent symbols (C)";
    clearSentEl.setAttribute("aria-keyshortcuts", "C");
}

function classifyRhythmGap(event) {
    const leading = event.leading_gap || "none";
    if (leading === "none") return "none";

    const wordGapMs = Number(keyConfig?.word_gap_ms);
    const gapMs = Number(event.leading_gap_ms);
    if (!Number.isFinite(wordGapMs) || wordGapMs <= 0 || !Number.isFinite(gapMs)) {
        return leading === "word" ? "amber" : "green";
    }

    if (gapMs < wordGapMs * 0.8) return "green";
    if (gapMs < wordGapMs * 1.3) return "amber";
    return "red";
}

function rhythmGapLabel(event) {
    const zone = classifyRhythmGap(event);
    if (zone === "none") return "first symbol";
    const gapMs = Number(event.leading_gap_ms);
    const wordGapMs = Number(keyConfig?.word_gap_ms);
    const gapText = formatMs(gapMs);
    const reference = Number.isFinite(wordGapMs) && wordGapMs > 0
        ? ` / word gap ${formatMs(wordGapMs)}`
        : "";
    if (zone === "green") return `${gapText}${reference}: green zone`;
    if (zone === "amber") return `${gapText}${reference}: amber boundary`;
    return `${gapText}${reference}: red separation`;
}

function rhythmGapScale(event) {
    const wordGapMs = Number(keyConfig?.word_gap_ms);
    const gapMs = Number(event.leading_gap_ms);
    if (!Number.isFinite(wordGapMs) || wordGapMs <= 0 || !Number.isFinite(gapMs)) {
        return 1;
    }
    return clamp(gapMs / wordGapMs, 0.35, 1.75);
}

function renderRhythmReview() {
    if (!rhythmReviewSymbolsEl || !rhythmReviewMetaEl) return;
    rhythmReviewSymbolsEl.replaceChildren();
    rhythmReviewMetaEl.textContent = sentReviewEvents.length === 0
        ? "no symbols"
        : `${sentReviewEvents.length} symbols / timing zones`;

    const fragment = document.createDocumentFragment();
    sentReviewEvents.forEach((event) => {
        const symbol = event.symbol || "?";
        const leading = event.leading_gap || "none";
        const zone = classifyRhythmGap(event);
        const item = document.createElement("li");
        item.classList.add(
            `key-rhythm-review__item--leading-${leading}`,
            `key-rhythm-review__item--zone-${zone}`,
        );
        item.title = rhythmGapLabel(event);
        item.style.setProperty("--key-rhythm-gap-scale", rhythmGapScale(event).toFixed(2));

        const symbolEl = document.createElement("span");
        symbolEl.className = "key-rhythm-review__symbol";
        symbolEl.textContent = symbol;

        const markerEl = document.createElement("span");
        markerEl.className = "key-rhythm-review__marker";
        markerEl.setAttribute("aria-hidden", "true");

        item.append(symbolEl, markerEl);
        fragment.appendChild(item);
    });
    rhythmReviewSymbolsEl.appendChild(fragment);
}

function setRhythmReviewExpanded(expanded) {
    if (!rhythmReviewToggleEl || !rhythmReviewArrowEl || !rhythmReviewBodyEl) return;
    rhythmReviewToggleEl.setAttribute("aria-expanded", String(expanded));
    rhythmReviewArrowEl.textContent = expanded ? "▼" : "▶";
    rhythmReviewBodyEl.hidden = !expanded;
}

function clearSentSymbols() {
    sentSymbolEl.textContent = "—";
    sentHistoryEl.replaceChildren();
    sentReviewEvents = [];
    lastSentEndedAt = null;
    copyProgress = 0;
    renderRhythmReview();
    diagGapEl.textContent = "none";
    resetHHClearTracker();
    recordDiagnostic("sent-symbols-clear");
}

function midiMessageToNoteEvent(message) {
    const [status, note, velocity = 0] = message.data;
    const command = status & 0xf0;
    if (command !== 0x80 && command !== 0x90) return null;

    // message.timeStamp is the CoreMIDI/Web MIDI arrival time in the same
    // domain as performance.now() — using it directly preserves hardware
    // timing through any JS dispatch jitter.
    return {
        note,
        pressed: command === 0x90 && velocity !== 0,
        timestamp: message.timeStamp / 1000,
    };
}

function pageAcceptsMidiInput() {
    // Visibility, not focus: a brief click on another app window is not a
    // reason to drop input. The visibilitychange handler covers genuine
    // off-screen states (tab switched away, window minimised).
    return document.visibilityState === "visible";
}

function focusLabel() {
    const visibility = document.visibilityState;
    const focus = document.hasFocus() ? "focused" : "blurred";
    return `${visibility} / ${focus}`;
}

// rAF-batched diagnostic rendering. The MIDI handler runs on the same thread
// as DOM mutations; doing per-event row inserts and textContent writes there
// produces timing jitter that compounds with itself. Queue work synchronously
// and flush in one animation frame so the main thread stays available for
// the next MIDI message.
const pendingRawDiagnosticRows = [];
let pendingDiagRawText = null;
let pendingDiagEventText = null;
let pendingDiagElementText = null;
let diagnosticRenderScheduled = false;

function scheduleDiagnosticRender() {
    if (diagnosticRenderScheduled) return;
    diagnosticRenderScheduled = true;
    requestAnimationFrame(flushDiagnosticRender);
}

function flushDiagnosticRender() {
    diagnosticRenderScheduled = false;

    if (pendingDiagRawText !== null) {
        diagRawEl.textContent = pendingDiagRawText;
        pendingDiagRawText = null;
    }
    if (pendingDiagEventText !== null) {
        diagEventEl.textContent = pendingDiagEventText;
        pendingDiagEventText = null;
    }
    if (pendingDiagElementText !== null) {
        diagElementEl.textContent = pendingDiagElementText;
        pendingDiagElementText = null;
    }

    if (pendingRawDiagnosticRows.length === 0) return;

    const fragment = document.createDocumentFragment();
    // Newest entry first; queue is in arrival order, so iterate reversed.
    for (let i = pendingRawDiagnosticRows.length - 1; i >= 0; i -= 1) {
        const entry = pendingRawDiagnosticRows[i];
        const row = document.createElement("tr");
        const timestampCell = document.createElement("td");
        const eventCell = document.createElement("td");
        const actionCell = document.createElement("td");
        const focusCell = document.createElement("td");
        timestampCell.textContent = entry.timestamp;
        eventCell.textContent = entry.event;
        actionCell.textContent = entry.action;
        focusCell.textContent = entry.focus;
        row.append(timestampCell, eventCell, actionCell, focusCell);
        fragment.appendChild(row);
    }
    pendingRawDiagnosticRows.length = 0;
    diagRawLogEl.prepend(fragment);
    while (diagRawLogEl.children.length > MAX_RAW_DIAGNOSTIC_ROWS) {
        diagRawLogEl.lastElementChild.remove();
    }
}

function queueDiagEvent(text) {
    pendingDiagEventText = text;
    scheduleDiagnosticRender();
}

function queueDiagElement(text) {
    pendingDiagElementText = text;
    scheduleDiagnosticRender();
}

function appendRawDiagnosticRow(event, action, kind = null) {
    const resolvedKind = kind || kindForNote(event.note) || "unknown";
    const state = event.pressed ? "down" : "up";
    pendingDiagRawText = `${resolvedKind} ${state} / note ${event.note} / ${action}`;
    pendingRawDiagnosticRows.push({
        timestamp: formatTimestamp(),
        event: `${resolvedKind} ${state} / note ${event.note}`,
        action,
        focus: focusLabel(),
    });
    scheduleDiagnosticRender();
}

function handleFormedBrowserMidiEvent(event) {
    const kind = kindForNote(event.note);
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

    // The Trinkey firmware emits already-formed elements (note-on + note-off
    // per dit/dah). Pass them straight through to sidetone and server decoder.
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
        pendingRawOns.push({ kind, note: event.note, timestamp: Number(event.timestamp) });
        sidetone.keyDown(event.note);
    } else {
        sidetone.keyUp(event.note);
    }
    updateAudioDiagnostic();
    if (activeSocket?.readyState === WebSocket.OPEN) {
        activeSocket.send(JSON.stringify({ action: "key-note-event", ...event }));
    }
}

function selectMidiInput(inputs) {
    const available = Array.from(inputs.values());
    return available.find((input) => input.name?.toLowerCase().includes("trrs trinkey"))
        || available[0]
        || null;
}

async function startBrowserMidi(socket) {
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
            handleFormedBrowserMidiEvent(event);
        };

        // Send the current performance.now() so the server can calibrate
        // browser timestamps into its time.monotonic() domain. Without this
        // the decoder's flush-time arithmetic would mix clock epochs.
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

function buildSequenceRow() {
    sequenceRow.replaceChildren();
    KOCH_ORDER.forEach((sym) => {
        const token = document.createElement("span");
        token.textContent = sym;
        token.dataset.symbol = sym;
        token.dataset.state = "available";
        token.setAttribute("role", "listitem");
        token.classList.add("seq-token");
        sequenceRow.appendChild(token);
    });
}

function setSequenceTokenPlaying(symbol, playing) {
    sequenceRow.querySelectorAll("[data-playing]").forEach((el) => {
        delete el.dataset.playing;
    });
    if (!playing || !symbol) return;
    const token = sequenceRow.querySelector(`[data-symbol="${CSS.escape(symbol)}"]`);
    if (token) token.dataset.playing = "true";
}

function renderSequence(state) {
    const claimedSet = new Set(state.symbols);
    claimedSymbolSet = claimedSet;
    const next = state.suggested_next;

    KOCH_ORDER.forEach((sym) => {
        const token = sequenceRow.querySelector(`[data-symbol="${CSS.escape(sym)}"]`);
        if (!token) return;

        if (claimedSet.has(sym)) {
            token.dataset.state = "claimed";
            token.title = `${sym} — known`;
        } else if (sym === next) {
            token.dataset.state = "next";
            token.title = `${sym} — next in sequence`;
        } else {
            token.dataset.state = "available";
            token.title = `${sym} — not yet known`;
        }
    });
}

function requestCopyExercises() {
    if (!copyHistoryEl) return;
    if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) return;
    activeSocket.send(JSON.stringify({ action: "request-copy-exercises" }));
}

let selectedCopyIndex = 0;
let copyExercises = [];
// Per-step expectation: { symbol, leading } where leading is "none", "word",
// or "character" — same vocabulary the engine emits on sent-symbol events.
let expectedCopySteps = [];
let copyProgress = 0;

function buildExpectedCopySteps(exercise) {
    const steps = [];
    const words = (exercise || "").split(" ");
    words.forEach((word, wordIdx) => {
        for (let i = 0; i < word.length; i++) {
            const leading = wordIdx === 0 && i === 0
                ? "none"
                : i === 0
                ? "word"
                : "character";
            steps.push({ symbol: word[i], leading });
        }
    });
    return steps;
}

function updateExpectedCopySteps() {
    expectedCopySteps = buildExpectedCopySteps(copyExercises[selectedCopyIndex]);
    copyProgress = 0;
}

// Walk a single pointer through the expected steps. The first step accepts
// any leading gap (the learner could be starting fresh, mid-stream, or after
// a clear); every subsequent step requires both the symbol AND the leading
// gap to match — so "MUM" only passes for one-word keying, not "M UM".
function noteCopySymbolForProgress(symbol, leadingGap) {
    if (expectedCopySteps.length === 0) return;
    const expected = expectedCopySteps[copyProgress];
    const symbolMatches = symbol === expected.symbol;
    const gapMatches = copyProgress === 0 || leadingGap === expected.leading;

    if (symbolMatches && gapMatches) {
        copyProgress += 1;
        if (copyProgress >= expectedCopySteps.length) {
            copyProgress = 0;
            if (selectedCopyIndex + 1 < copyExercises.length) {
                selectCopyExercise(selectedCopyIndex + 1);
            } else {
                requestCopyExercises();
            }
        }
        return;
    }

    // Mismatch — fall back to step 0. If this symbol matches step 0's symbol,
    // count the current input as the start of a fresh attempt.
    copyProgress = symbol === expectedCopySteps[0].symbol ? 1 : 0;
}

// TODO(cadence): if the HH-clear dev toggle is on (Settings → Developer),
// keying "HH" clears the Sent area. The random exercises the engine emits
// can still contain "HH" — once H joins the claimed set, keying such an
// exercise as displayed would inadvertently clear the learner's work.
// Either filter incoming exercises here, or pass the toggle state up so the
// generator suppresses HH at source. See web/js/hh-clear.js.
function renderCopyExercises(event) {
    if (!copyHistoryEl || !copySymbolEl) return;
    const exercises = Array.isArray(event.exercises) ? event.exercises : [];
    copyHistoryEl.replaceChildren();
    selectedCopyIndex = 0;
    copyExercises = exercises;
    updateExpectedCopySteps();
    if (exercises.length === 0) {
        copySymbolEl.textContent = "—";
        return;
    }
    exercises.forEach((exercise, idx) => {
        const item = document.createElement("li");
        item.className = "key-copy-history__item";
        item.dataset.exercise = exercise;
        if (idx === selectedCopyIndex) item.dataset.selected = "true";
        const row = document.createElement("div");
        row.className = "key-copy-history__row";
        const words = exercise.split(" ");
        words.forEach((word, wordIdx) => {
            for (let i = 0; i < word.length; i++) {
                const leading =
                    wordIdx === 0 && i === 0
                        ? "none"
                        : i === 0
                        ? "word"
                        : "character";
                const charEl = document.createElement("span");
                charEl.className =
                    `key-copy-history__symbol key-copy-history__symbol--leading-${leading}`;
                charEl.textContent = word[i];
                row.appendChild(charEl);
            }
        });
        item.appendChild(row);
        copyHistoryEl.appendChild(item);
    });
    copySymbolEl.textContent = exercises[selectedCopyIndex];
}

function selectCopyExercise(idx) {
    if (!copyHistoryEl || !copySymbolEl) return false;
    const items = copyHistoryEl.querySelectorAll(".key-copy-history__item");
    if (idx < 0 || idx >= items.length) return false;
    selectedCopyIndex = idx;
    items.forEach((item, i) => {
        if (i === idx) item.dataset.selected = "true";
        else delete item.dataset.selected;
    });
    copySymbolEl.textContent = items[idx].dataset.exercise || "";
    updateExpectedCopySteps();
    return true;
}

function clearCopyExercises() {
    if (!copyHistoryEl || !copySymbolEl) return;
    copySymbolEl.textContent = "—";
    copyHistoryEl.replaceChildren();
    selectedCopyIndex = 0;
    copyExercises = [];
    updateExpectedCopySteps();
}

function renderSentSymbol(event) {
    const symbol = event.symbol || "?";
    const startedAt = Number(event.started_at);
    const endedAt = Number(event.ended_at);
    const leadingGapMs = Number.isFinite(startedAt) && Number.isFinite(lastSentEndedAt)
        ? Math.max(0, (startedAt - lastSentEndedAt) * 1000)
        : null;
    const reviewEvent = { ...event, symbol, leading_gap_ms: leadingGapMs };

    sentSymbolEl.textContent = symbol;
    diagGapEl.textContent = event.leading_gap || "none";
    recordDiagnostic("sent-symbol", {
        symbol,
        pattern: event.pattern,
        leading_gap: event.leading_gap || "none",
        leading_gap_ms: leadingGapMs,
        started_at: event.started_at,
        ended_at: event.ended_at,
    });
    appendDiagnosticRow(event);

    const item = document.createElement("li");
    const leading = event.leading_gap || "none";
    item.classList.add(`key-sent-history__item--leading-${leading}`);
    const symbolEl = document.createElement("span");
    symbolEl.className = "key-sent-history__symbol";
    symbolEl.textContent = symbol;
    item.append(symbolEl);
    sentHistoryEl.appendChild(item);

    while (sentHistoryEl.children.length > MAX_SENT_HISTORY) {
        sentHistoryEl.firstElementChild.remove();
    }

    sentReviewEvents.push(reviewEvent);
    while (sentReviewEvents.length > MAX_SENT_HISTORY) {
        sentReviewEvents.shift();
    }
    if (Number.isFinite(endedAt)) {
        lastSentEndedAt = endedAt;
    }
    renderRhythmReview();
    noteSentSymbol(symbol, event.leading_gap, clearSentSymbols);
    noteCopySymbolForProgress(symbol, event.leading_gap || "none");
}

function renderKeyInputStart(event) {
    keyConfig = event;
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

function appendDiagnosticRow(event) {
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

function renderKeyEvent(event) {
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

function renderKeyInputReset(event) {
    pendingGeneratedOns = [];
    pendingRawOns = [];
    queueDiagEvent(`input reset / ${event.reason || "manual"}`);
    recordDiagnostic("key-input-reset", { reason: event.reason || null });
}

function renderError(event) {
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

function connect() {
    setStatus("connecting", "connecting...");
    const socket = new WebSocket(wsUrl);
    activeSocket = socket;

    socket.addEventListener("open", () => {
        recordDiagnostic("websocket", { state: "open", url: wsUrl });
        setStatus("connected", "connected");
        startBrowserMidi(socket);
    });

    socket.addEventListener("message", (message) => {
        const event = JSON.parse(message.data);
        if (event.type === "claimed-symbols") {
            renderSequence(event);
            // Cadence page only — refresh exercises when the claimed set changes.
            requestCopyExercises();
        } else if (event.type === "copy-exercises") {
            renderCopyExercises(event);
        } else if (event.type === "sent-symbol") {
            renderSentSymbol(event);
        } else if (event.type === "key-input-start") {
            renderKeyInputStart(event);
        } else if (event.type === "key-event") {
            renderKeyEvent(event);
        } else if (event.type === "key-input-reset") {
            renderKeyInputReset(event);
        } else if (event.type === "morse-repeat-start") {
            setSequenceTokenPlaying(event.symbol, true);
        } else if (event.type === "morse-repeat-end") {
            setSequenceTokenPlaying(event.symbol, false);
        } else if (event.type === "error") {
            renderError(event);
        }
    });

    socket.addEventListener("close", () => {
        recordDiagnostic("websocket", { state: "close", url: wsUrl });
        setSequenceTokenPlaying(null, false);
        sidetone.mute();
        if (browserMidiInput) {
            browserMidiInput.onmidimessage = null;
            browserMidiInput = null;
        }
        if (activeSocket === socket) {
            activeSocket = null;
        }
        setStatus("connecting", "disconnected");
    });
}

buildSequenceRow();
document.addEventListener("visibilitychange", () => {
    recordDiagnostic("page-lifecycle", {
        event: "visibilitychange",
        visibility: document.visibilityState,
    });
    if (document.visibilityState === "hidden") {
        setMidiInputArmed(false, "page hidden");
    } else if (document.visibilityState === "visible" && !midiInputArmed) {
        setMidiInputArmed(true, "page visible");
    }
});
keyInputToggleEl.addEventListener("click", () => {
    setMidiInputArmed(!midiInputArmed, "manual toggle");
});
copyDiagnosticsEl.addEventListener("click", async () => {
    const previousText = copyDiagnosticsEl.textContent;
    const text = diagnosticText();
    try {
        await navigator.clipboard.writeText(text);
        copyDiagnosticsEl.textContent = "copied";
        recordDiagnostic("diagnostics-copy", { status: "clipboard", bytes: text.length });
    } catch {
        window.prompt("Copy diagnostics", text);
        copyDiagnosticsEl.textContent = "copy shown";
        recordDiagnostic("diagnostics-copy", { status: "prompt", bytes: text.length });
    }
    window.setTimeout(() => {
        copyDiagnosticsEl.textContent = previousText;
    }, 1200);
});
soundToggleEl.addEventListener("click", async () => {
    if (soundEnabled) {
        soundEnabled = false;
        sidetone.mute();
    } else {
        soundEnabled = await sidetone.unlock();
    }
    updateAudioDiagnostic();
});
clearSentEl.addEventListener("click", clearSentSymbols);
if (rhythmReviewToggleEl) {
    rhythmReviewToggleEl.addEventListener("click", () => {
        const expanded = rhythmReviewToggleEl.getAttribute("aria-expanded") === "true";
        setRhythmReviewExpanded(!expanded);
    });
}

// Cadence preview: Left Alt + symbol-key plays the symbol's bare Morse
// three times through the engine output. event.code is used because
// Option+letter on macOS substitutes characters in event.key. Scoped to
// the Cadence page via copyHistoryEl; the Sequence grid on Freeplay is
// the same DOM but lacks the Copy section that motivates the preview.
const PREVIEW_CODE_TO_SYMBOL = (() => {
    const map = new Map();
    for (let i = 0; i < 26; i++) {
        map.set(`Key${String.fromCharCode(65 + i)}`, String.fromCharCode(65 + i));
    }
    for (let i = 0; i <= 9; i++) {
        map.set(`Digit${i}`, String(i));
    }
    map.set("Period", ".");
    map.set("Comma", ",");
    map.set("Equal", "=");
    return map;
})();

function symbolForPreviewCode(code, shiftKey) {
    if (code === "Slash") return shiftKey ? "?" : "/";
    return PREVIEW_CODE_TO_SYMBOL.get(code) || null;
}

window.addEventListener("keydown", (event) => {
    if (event.code === "AltLeft") {
        leftAltDown = true;
        return;
    }
    if (!leftAltDown || !event.altKey) return;
    if (!copyHistoryEl) return;
    if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
    }
    const symbol = symbolForPreviewCode(event.code, event.shiftKey);
    if (!symbol) return;
    if (!claimedSymbolSet.has(symbol)) return;
    event.preventDefault();
    if (event.repeat) return;
    activeSocket.send(JSON.stringify({ action: "play-morse-repeat", symbol }));
});

window.addEventListener("keyup", (event) => {
    if (event.code === "AltLeft") {
        leftAltDown = false;
    }
});

window.addEventListener("blur", () => {
    leftAltDown = false;
});

window.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
    }
    const key = event.key.toLowerCase();
    if (soundEnabled && key === "m") {
        event.preventDefault();
        toggleSidetone();
    } else if (!soundEnabled && key === "s") {
        event.preventDefault();
        toggleSidetone();
    } else if (key === "c") {
        event.preventDefault();
        clearSentSymbols();
    } else if (/^[1-9]$/.test(key)) {
        if (selectCopyExercise(parseInt(key, 10) - 1)) {
            event.preventDefault();
        }
    }
});
renderClearSentLabel();
renderRhythmReview();
updateAudioDiagnostic();
connect();
