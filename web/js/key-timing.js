// Copy — Key timing page.
//
// Read-only sequence display for known symbols. The engine pushes the same
// claimed-symbols event used by Koch Exercises; this page only renders it.

const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
const wsUrl = `${wsProtocol}//${location.host}/ws`;

const statusEl = document.querySelector(".status");
const sequenceRow = document.getElementById("sequence-row");
const sentSymbolEl = document.getElementById("sent-symbol");
const sentPatternEl = document.getElementById("sent-pattern");
const sentHistoryEl = document.getElementById("sent-history");
const soundToggleEl = document.getElementById("key-sound-toggle");
const keyInputToggleEl = document.getElementById("key-input-toggle");
const keyDeviceResetEl = document.getElementById("key-device-reset");
const copyDiagnosticsEl = document.getElementById("copy-diagnostics");
const diagInputEl = document.getElementById("diag-input");
const diagAudioEl = document.getElementById("diag-audio");
const diagEventEl = document.getElementById("diag-event");
const diagRawEl = document.getElementById("diag-raw");
const diagKeyerEl = document.getElementById("diag-keyer");
const diagElementEl = document.getElementById("diag-element");
const diagGapEl = document.getElementById("diag-gap");
const diagTimingEl = document.getElementById("diag-timing");
const diagLogEl = document.getElementById("diag-log");
const diagRawLogEl = document.getElementById("diag-raw-log");

const MAX_SENT_HISTORY = 8;
const MAX_DIAGNOSTIC_ROWS = 24;
const MAX_RAW_DIAGNOSTIC_ROWS = 32;
const MAX_DIAGNOSTIC_EVENTS = 240;
const DEFAULT_TONE_HZ = 600;
const DEFAULT_AMPLITUDE = 0.3;
const DEFAULT_RAMP_SECONDS = 0.005;
const DEFAULT_DIT_MS = 100;
const STUCK_PADDLE_MS = 2000;
const BROWSER_MIDI_INPUT_MODE = "formed-elements";
const MAX_CONSECUTIVE_SAME_FORMED_ELEMENTS = 5;
const TRINKEY_IAMBIC_A_MODE = 7;

let keyConfig = null;
let soundEnabled = false;
let pendingGeneratedOns = [];
let pendingRawOns = [];
let browserMidiAccess = null;
let browserMidiInput = null;
let browserMidiOutput = null;
let activeSocket = null;
let diagnosticEvents = [];
let formedElementGuard = newFormedElementGuard();
let midiInputArmed = true;

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

function newFormedElementGuard() {
    return {
        activeStarts: new Map(),
        blockedUntil: 0,
        lastKind: null,
        lastEndedAt: null,
        consecutiveSame: 0,
    };
}

function resetFormedElementGuard() {
    formedElementGuard = newFormedElementGuard();
}

function characterGapSeconds() {
    return (Number(keyConfig?.character_gap_ms) || DEFAULT_DIT_MS * 3) / 1000;
}

function shouldAcceptFormedEvent(event, kind) {
    const now = Number(event.timestamp);
    if (Number.isFinite(formedElementGuard.blockedUntil)) {
        if (now < formedElementGuard.blockedUntil) {
            return false;
        }
        if (formedElementGuard.blockedUntil > 0) {
            resetFormedElementGuard();
        }
    }

    if (event.pressed) {
        formedElementGuard.activeStarts.set(event.note, now);
        return true;
    }

    formedElementGuard.activeStarts.delete(event.note);

    // The firmware is currently sending already-formed Morse elements. A valid
    // symbol in our current table never needs more than five identical elements
    // in a row inside one character. If we see a sixth dit or dah before a
    // character gap, that is a runaway MIDI stream, not intentional sending.
    const gap = formedElementGuard.lastEndedAt === null
        ? Number.POSITIVE_INFINITY
        : now - formedElementGuard.lastEndedAt;
    if (gap >= characterGapSeconds()) {
        formedElementGuard.consecutiveSame = 1;
    } else if (formedElementGuard.lastKind === kind) {
        formedElementGuard.consecutiveSame += 1;
    } else {
        formedElementGuard.consecutiveSame = 1;
    }

    formedElementGuard.lastKind = kind;
    formedElementGuard.lastEndedAt = now;

    if (formedElementGuard.consecutiveSame > MAX_CONSECUTIVE_SAME_FORMED_ELEMENTS) {
        formedElementGuard.blockedUntil = now + characterGapSeconds();
        sidetone.mute();
        recordDiagnostic("formed-runaway-guard", {
            kind,
            note: event.note,
            consecutive_same: formedElementGuard.consecutiveSame,
            blocked_until: formedElementGuard.blockedUntil,
        });
        diagEventEl.textContent = `runaway ${kind} stream blocked`;
        return false;
    }

    return true;
}

function recordDiagnostic(type, details = {}) {
    diagnosticEvents.push({
        at: new Date().toISOString(),
        t_ms: Math.round(performance.now()),
        type,
        focus: focusLabel(),
        keyer: browserIambicKeyer?.snapshot?.() || null,
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
        midi_output_name: browserMidiOutput?.name || null,
        key_config: keyConfig,
        browser_midi_input_mode: BROWSER_MIDI_INPUT_MODE,
        keyer: browserIambicKeyer.snapshot(),
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
        resetFormedElementGuard();
    }
    recordDiagnostic("midi-input-arm", { armed, reason });
    diagEventEl.textContent = armed ? "input armed" : `input disarmed / ${reason}`;
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

class BrowserIambicAKeyer {
    constructor() {
        this.socket = null;
        this.physicalDown = new Set();
        this.blockedUntilRelease = new Set();
        this.state = "idle";
        this.currentKind = null;
        this.lastKind = null;
        this.queuedKind = null;
        this.markTimer = null;
        this.gapTimer = null;
        this.stuckTimer = null;
    }

    handlePhysicalEvent(event, socket) {
        const kind = this.kindForNote(event.note);
        if (!kind || !keyConfig) {
            appendRawDiagnosticRow(event, "ignored / unmapped");
            recordDiagnostic("raw-midi", {
                note: event.note,
                pressed: event.pressed,
                action: "ignored / unmapped",
            });
            return;
        }

        if (!pageAcceptsMidiInput()) {
            appendRawDiagnosticRow(event, "ignored / background");
            recordDiagnostic("raw-midi", {
                kind,
                note: event.note,
                pressed: event.pressed,
                action: "ignored / background",
            });
            this.panic("background midi ignored / all paddles released");
            return;
        }

        this.socket = socket;

        // The Trinkey is reporting paddle contact state here, not completed
        // Morse elements. A squeeze can therefore overlap note 1 and note 2.
        // We keep that raw state separate from the formed elements emitted to
        // the server so a held dah contact does not become one long dah.
        if (event.pressed) {
            if (this.blockedUntilRelease.has(kind)) {
                appendRawDiagnosticRow(event, "ignored / release required", kind);
                diagEventEl.textContent = `raw ${kind} down ignored / release required`;
                recordDiagnostic("raw-midi", {
                    kind,
                    note: event.note,
                    pressed: true,
                    action: "ignored / release required",
                });
                return;
            }
            if (this.physicalDown.has(kind)) {
                appendRawDiagnosticRow(event, "ignored / duplicate down", kind);
                diagEventEl.textContent = `raw ${kind} duplicate down ignored / note ${event.note}`;
                recordDiagnostic("raw-midi", {
                    kind,
                    note: event.note,
                    pressed: true,
                    action: "ignored / duplicate down",
                });
                return;
            }

            appendRawDiagnosticRow(event, "accepted", kind);
            recordDiagnostic("raw-midi", {
                kind,
                note: event.note,
                pressed: true,
                action: "accepted",
            });
            pendingRawOns.push({ kind, note: event.note, timestamp: Number(event.timestamp) });
            this.physicalDown.add(kind);
            diagEventEl.textContent = `raw ${kind} down / note ${event.note}`;
            this.scheduleStuckGuard();
            this.updateKeyerDiagnostic();
            this.press(kind);
            return;
        }

        this.blockedUntilRelease.delete(kind);
        if (!this.physicalDown.has(kind)) {
            appendRawDiagnosticRow(event, "ignored / duplicate up", kind);
            diagEventEl.textContent = `raw ${kind} duplicate up ignored / note ${event.note}`;
            recordDiagnostic("raw-midi", {
                kind,
                note: event.note,
                pressed: false,
                action: "ignored / duplicate up",
            });
            return;
        }

        appendRawDiagnosticRow(event, "accepted", kind);
        recordDiagnostic("raw-midi", {
            kind,
            note: event.note,
            pressed: false,
            action: "accepted",
        });
        this.physicalDown.delete(kind);
        diagEventEl.textContent = `raw ${kind} up / note ${event.note}`;
        this.scheduleStuckGuard();
        this.updateKeyerDiagnostic();
    }

    press(kind) {
        if (this.state === "idle") {
            recordDiagnostic("keyer-decision", { action: "start", kind });
            this.startElement(kind);
            return;
        }

        // Iambic A is driven by paddle intent at element boundaries. If the
        // opposite paddle is pressed while an element or its following one-dit
        // gap is active, remember one opposite element. That handles normal
        // squeeze timing without letting stale held contacts create a long mark.
        const referenceKind = this.currentKind || this.lastKind;
        if (referenceKind && kind !== referenceKind) {
            this.queuedKind = kind;
            recordDiagnostic("keyer-decision", {
                action: "queue-opposite",
                kind,
                reference_kind: referenceKind,
            });
        }
    }

    kindForNote(note) {
        if (note === keyConfig?.dit_note) return "dit";
        if (note === keyConfig?.dah_note) return "dah";
        return null;
    }

    noteForKind(kind) {
        return kind === "dit" ? keyConfig?.dit_note : keyConfig?.dah_note;
    }

    ditMs() {
        return Number(keyConfig?.dit_ms_expected) || DEFAULT_DIT_MS;
    }

    elementMs(kind) {
        return kind === "dah" ? this.ditMs() * 3 : this.ditMs();
    }

    startElement(kind) {
        const note = this.noteForKind(kind);
        if (!Number.isFinite(note)) return;

        this.clearMarkTimer();
        this.clearGapTimer();
        this.state = "mark";
        this.currentKind = kind;
        this.lastKind = kind;
        this.updateKeyerDiagnostic();
        this.emitFormedEvent(note, true);
        this.markTimer = window.setTimeout(() => {
            this.markTimer = null;
            this.finishElement(kind, note);
        }, this.elementMs(kind));
    }

    finishElement(kind, note) {
        this.emitFormedEvent(note, false);
        this.currentKind = null;
        this.state = "gap";
        this.updateKeyerDiagnostic();
        this.gapTimer = window.setTimeout(() => {
            this.gapTimer = null;
            this.advanceAfterGap();
        }, this.ditMs());
    }

    advanceAfterGap() {
        const nextKind = this.nextKind();
        if (nextKind) {
            this.startElement(nextKind);
            return;
        }

        this.state = "idle";
        this.currentKind = null;
        this.updateKeyerDiagnostic();
    }

    nextKind() {
        if (this.queuedKind) {
            const kind = this.queuedKind;
            this.queuedKind = null;
            return kind;
        }

        // Stop same-paddle free-running for now. We have observed raw MIDI
        // "down" state arriving while the operator is not touching the key.
        // If we repeat the same held paddle, one stale dit contact becomes an
        // endless stream of dits. Continuing only to the opposite held paddle
        // keeps iambic squeeze formation working: dah->dit->dah for K, or
        // dit->dah->dit for R, while a lone stale dit/dah dies after one mark.
        if (!this.lastKind) {
            return null;
        }
        const alternateKind = this.lastKind === "dit" ? "dah" : "dit";
        if (this.physicalDown.has(alternateKind)) {
            recordDiagnostic("keyer-decision", {
                action: "continue-alternate",
                kind: alternateKind,
                previous_kind: this.lastKind,
            });
            return alternateKind;
        }
        recordDiagnostic("keyer-decision", { action: "stop-after-gap" });
        return null;
    }

    emitFormedEvent(note, pressed) {
        if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;

        const event = {
            note,
            pressed,
            timestamp: performance.now() / 1000,
        };

        // Sidetone follows the clean generated element, not the physical
        // paddle contact. That is the key difference that prevents squeeze
        // overlap from sounding like a stuck key.
        if (pressed) {
            sidetone.keyDown(note);
        } else {
            sidetone.keyUp(note);
        }
        updateAudioDiagnostic();
        recordDiagnostic("generated-key-event", {
            kind: this.kindForNote(note),
            note,
            pressed,
        });
        this.socket.send(JSON.stringify({ action: "key-note-event", ...event }));
    }

    panic(reason) {
        // Browser MIDI can miss release edges when a tab loses focus, a device
        // disconnects, or the page is backgrounded. In that situation we force
        // all local state up and ignore those paddles until we see a real up
        // edge, otherwise a stale "down" can repeat forever in the keyer.
        for (const kind of this.physicalDown) {
            this.blockedUntilRelease.add(kind);
        }
        recordDiagnostic("panic", { reason });
        this.physicalDown.clear();
        this.queuedKind = null;
        this.clearMarkTimer();
        this.clearGapTimer();
        this.clearStuckTimer();

        for (const kind of ["dit", "dah"]) {
            const note = this.noteForKind(kind);
            if (Number.isFinite(note)) {
                sidetone.keyUp(note);
                this.sendRelease(note);
            }
        }

        this.state = "idle";
        this.currentKind = null;
        diagEventEl.textContent = reason;
        this.updateKeyerDiagnostic();
        updateAudioDiagnostic();
    }

    sendRelease(note) {
        if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;
        this.socket.send(JSON.stringify({
            action: "key-note-event",
            note,
            pressed: false,
            timestamp: performance.now() / 1000,
        }));
    }

    scheduleStuckGuard() {
        this.clearStuckTimer();
        if (this.physicalDown.size === 0) return;

        this.stuckTimer = window.setTimeout(() => {
            this.stuckTimer = null;
            this.panic("stuck paddle released");
        }, STUCK_PADDLE_MS);
    }

    clearMarkTimer() {
        if (this.markTimer) {
            window.clearTimeout(this.markTimer);
            this.markTimer = null;
        }
    }

    clearGapTimer() {
        if (this.gapTimer) {
            window.clearTimeout(this.gapTimer);
            this.gapTimer = null;
        }
    }

    clearStuckTimer() {
        if (this.stuckTimer) {
            window.clearTimeout(this.stuckTimer);
            this.stuckTimer = null;
        }
    }

    snapshot() {
        return {
            state: this.state,
            current_kind: this.currentKind,
            last_kind: this.lastKind,
            queued_kind: this.queuedKind,
            physical_down: [...this.physicalDown],
            blocked_until_release: [...this.blockedUntilRelease],
            has_mark_timer: Boolean(this.markTimer),
            has_gap_timer: Boolean(this.gapTimer),
            has_stuck_timer: Boolean(this.stuckTimer),
        };
    }

    updateKeyerDiagnostic() {
        const down = [...this.physicalDown].join("+") || "none";
        const blocked = [...this.blockedUntilRelease].join("+") || "none";
        diagKeyerEl.textContent = [
            `state ${this.state}`,
            `down ${down}`,
            `queued ${this.queuedKind || "none"}`,
            `blocked ${blocked}`,
        ].join(" / ");
    }
}

const browserIambicKeyer = new BrowserIambicAKeyer();

function canUseAppSidetone() {
    return soundEnabled && !keyConfig?.trinkey_buzzer_enabled;
}

function updateAudioDiagnostic() {
    diagAudioEl.textContent = sidetone.stateLabel();
    soundToggleEl.textContent = soundEnabled ? "mute" : "enable sound";
    soundToggleEl.disabled = Boolean(keyConfig?.trinkey_buzzer_enabled);
}

function midiMessageToNoteEvent(message) {
    const [status, note, velocity = 0] = message.data;
    const command = status & 0xf0;
    if (command !== 0x80 && command !== 0x90) return null;

    return {
        note,
        pressed: command === 0x90 && velocity !== 0,
        timestamp: performance.now() / 1000,
    };
}

function pageAcceptsMidiInput() {
    return document.visibilityState === "visible" && document.hasFocus();
}

function focusLabel() {
    const visibility = document.visibilityState;
    const focus = document.hasFocus() ? "focused" : "blurred";
    return `${visibility} / ${focus}`;
}

function appendRawDiagnosticRow(event, action, kind = null) {
    const resolvedKind = kind || browserIambicKeyer.kindForNote(event.note) || "unknown";
    const state = event.pressed ? "down" : "up";
    diagRawEl.textContent = `${resolvedKind} ${state} / note ${event.note} / ${action}`;

    const row = document.createElement("tr");
    const timestampCell = document.createElement("td");
    const eventCell = document.createElement("td");
    const actionCell = document.createElement("td");
    const focusCell = document.createElement("td");

    timestampCell.textContent = formatTimestamp();
    eventCell.textContent = `${resolvedKind} ${state} / note ${event.note}`;
    actionCell.textContent = action;
    focusCell.textContent = focusLabel();

    row.append(timestampCell, eventCell, actionCell, focusCell);
    diagRawLogEl.prepend(row);

    while (diagRawLogEl.children.length > MAX_RAW_DIAGNOSTIC_ROWS) {
        diagRawLogEl.lastElementChild.remove();
    }
}

function handleFormedBrowserMidiEvent(event) {
    const kind = browserIambicKeyer.kindForNote(event.note);
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
        appendRawDiagnosticRow(event, "ignored / background", kind);
        recordDiagnostic("raw-midi", {
            kind,
            note: event.note,
            pressed: event.pressed,
            action: "ignored / background",
            mode: BROWSER_MIDI_INPUT_MODE,
        });
        sidetone.keyUp(event.note);
        setMidiInputArmed(false, "background midi");
        browserIambicKeyer.panic("background formed midi ignored / all paddles released");
        return;
    }

    if (!shouldAcceptFormedEvent(event, kind)) {
        appendRawDiagnosticRow(event, "ignored / runaway guard", kind);
        recordDiagnostic("raw-midi", {
            kind,
            note: event.note,
            pressed: event.pressed,
            action: "ignored / runaway guard",
            mode: BROWSER_MIDI_INPUT_MODE,
        });
        setMidiInputArmed(false, "runaway guard");
        resetCopyKeyInput("runaway guard");
        sendTrinkeyRelease("runaway guard");
        if (!event.pressed) {
            sidetone.keyUp(event.note);
        }
        updateAudioDiagnostic();
        return;
    }

    // The pasted diagnostic log showed the TRRS Trinkey firmware is already
    // emitting formed elements: dit note pairs are about 60 ms and dah pairs
    // are about 180 ms. In that firmware mode we must not run a browser
    // iambic keyer on top of it. We pass the formed note events through to
    // sidetone and the server decoder, and keep raw diagnostics so any future
    // spontaneous note stream is clearly attributable to Web MIDI/hardware.
    appendRawDiagnosticRow(event, "accepted / formed pass-through", kind);
    recordDiagnostic("raw-midi", {
        kind,
        note: event.note,
        pressed: event.pressed,
        action: "accepted / formed pass-through",
        mode: BROWSER_MIDI_INPUT_MODE,
    });
    diagEventEl.textContent = `formed ${kind} ${event.pressed ? "down" : "up"} / note ${event.note}`;

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

function renderLocalBrowserKeyEvent(event) {
    if (BROWSER_MIDI_INPUT_MODE === "formed-elements") {
        handleFormedBrowserMidiEvent(event);
        return;
    }
    browserIambicKeyer.handlePhysicalEvent(event, activeSocket);
}

function selectMidiInput(inputs) {
    const available = Array.from(inputs.values());
    return available.find((input) => input.name?.toLowerCase().includes("trrs trinkey"))
        || available[0]
        || null;
}

function selectMidiOutput(outputs) {
    const available = Array.from(outputs.values());
    return available.find((output) => output.name?.toLowerCase().includes("trrs trinkey")) || null;
}

function updateDeviceResetButton() {
    if (!keyDeviceResetEl) return;
    keyDeviceResetEl.disabled = !browserMidiOutput;
    keyDeviceResetEl.title = browserMidiOutput
        ? "Release and reset the TRRS Trinkey keyer"
        : "No TRRS Trinkey MIDI output available";
}

function resetCopyKeyInput(reason) {
    if (activeSocket?.readyState !== WebSocket.OPEN) {
        recordDiagnostic("copy-key-input-reset", { status: "not connected", reason });
        return;
    }
    activeSocket.send(JSON.stringify({ action: "reset-key-input", reason }));
    recordDiagnostic("copy-key-input-reset", { status: "sent", reason });
}

function sendTrinkeyRelease(reason) {
    if (!browserMidiOutput && browserMidiAccess) {
        browserMidiOutput = selectMidiOutput(browserMidiAccess.outputs);
        updateDeviceResetButton();
    }
    if (!browserMidiOutput) {
        recordDiagnostic("trinkey-release", { status: "no output", reason });
        return false;
    }

    const messages = [
        [0x80, 0, 0],
        [0x80, keyConfig?.dit_note ?? 1, 0],
        [0x80, keyConfig?.dah_note ?? 2, 0],
        [0xC0, TRINKEY_IAMBIC_A_MODE],
        [0x80, 0, 0],
        [0x80, keyConfig?.dit_note ?? 1, 0],
        [0x80, keyConfig?.dah_note ?? 2, 0],
    ];

    try {
        messages.forEach((message) => browserMidiOutput.send(message));
        recordDiagnostic("trinkey-release", {
            status: "sent",
            reason,
            output_name: browserMidiOutput.name || "browser MIDI output",
            keyer_mode: TRINKEY_IAMBIC_A_MODE,
            messages,
        });
        return true;
    } catch (error) {
        recordDiagnostic("trinkey-release", {
            status: "failed",
            reason,
            error: error?.message || String(error),
        });
        return false;
    }
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
                browserIambicKeyer.panic("midi input changed / all paddles released");
            }
            if (event.port?.type === "output") {
                browserMidiOutput = selectMidiOutput(access.outputs);
                updateDeviceResetButton();
            }
        });
        const input = selectMidiInput(access.inputs);
        if (!input) {
            diagInputEl.textContent = "no browser MIDI input";
            socket.send(JSON.stringify({ action: "start-key-input" }));
            return;
        }
        browserMidiOutput = selectMidiOutput(access.outputs);
        updateDeviceResetButton();

        browserMidiInput = input;
        browserMidiInput.onmidimessage = (message) => {
            if (socket.readyState !== WebSocket.OPEN) return;
            recordDiagnostic("web-midi-message", {
                input_name: input.name || "browser MIDI",
                data: Array.from(message.data),
            });
            const event = midiMessageToNoteEvent(message);
            if (!event) return;
            renderLocalBrowserKeyEvent(event);
        };

        socket.send(JSON.stringify({
            action: "start-browser-key-input",
            input_name: input.name || "browser MIDI",
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

function renderSequence(state) {
    const claimedSet = new Set(state.symbols);
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

function renderSentSymbol(event) {
    const symbol = event.symbol || "?";
    sentSymbolEl.textContent = symbol;
    sentPatternEl.textContent = event.pattern;
    diagGapEl.textContent = event.leading_gap || "none";
    recordDiagnostic("sent-symbol", {
        symbol,
        pattern: event.pattern,
        leading_gap: event.leading_gap || "none",
        started_at: event.started_at,
        ended_at: event.ended_at,
    });
    appendDiagnosticRow(event);

    const item = document.createElement("li");
    const symbolEl = document.createElement("span");
    const patternEl = document.createElement("span");
    if (event.leading_gap === "word") {
        const gapEl = document.createElement("span");
        gapEl.className = "key-sent-history__gap";
        gapEl.textContent = "/";
        item.appendChild(gapEl);
    }
    symbolEl.className = "key-sent-history__symbol";
    patternEl.className = "key-sent-history__pattern";
    symbolEl.textContent = symbol;
    patternEl.textContent = event.pattern;
    item.append(symbolEl, patternEl);
    sentHistoryEl.appendChild(item);

    while (sentHistoryEl.children.length > MAX_SENT_HISTORY) {
        sentHistoryEl.firstElementChild.remove();
    }
}

function renderKeyInputStart(event) {
    keyConfig = event;
    resetFormedElementGuard();
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
    diagEventEl.textContent = `${event.kind} ${state} / note ${event.note}`;
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
            diagElementEl.textContent = [
                event.kind,
                formatMs(event.duration_ms),
                formatRatio(event.ratio_dits),
            ].join(" / ");
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
    resetFormedElementGuard();
    diagEventEl.textContent = `input reset / ${event.reason || "manual"}`;
    recordDiagnostic("key-input-reset", { reason: event.reason || null });
}

function renderError(event) {
    const reason = event.reason || "error";
    const detail = event.detail ? `: ${event.detail}` : "";
    recordDiagnostic("server-error", { reason, detail: event.detail || null });
    statusEl.title = `${reason}${detail}`;

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
        } else if (event.type === "sent-symbol") {
            renderSentSymbol(event);
        } else if (event.type === "key-input-start") {
            renderKeyInputStart(event);
        } else if (event.type === "key-event") {
            renderKeyEvent(event);
        } else if (event.type === "key-input-reset") {
            renderKeyInputReset(event);
        } else if (event.type === "error") {
            renderError(event);
        }
    });

    socket.addEventListener("close", () => {
        recordDiagnostic("websocket", { state: "close", url: wsUrl });
        browserIambicKeyer.panic("connection closed");
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
window.addEventListener("blur", () => {
    recordDiagnostic("page-lifecycle", { event: "blur" });
    setMidiInputArmed(false, "focus lost");
    browserIambicKeyer.panic("focus lost / all paddles released");
});
window.addEventListener("focus", () => {
    recordDiagnostic("page-lifecycle", { event: "focus" });
});
document.addEventListener("visibilitychange", () => {
    recordDiagnostic("page-lifecycle", {
        event: "visibilitychange",
        visibility: document.visibilityState,
    });
    if (document.visibilityState === "hidden") {
        setMidiInputArmed(false, "page hidden");
        browserIambicKeyer.panic("page hidden / all paddles released");
    }
});
keyInputToggleEl.addEventListener("click", () => {
    setMidiInputArmed(!midiInputArmed, "manual toggle");
});
keyDeviceResetEl.addEventListener("click", () => {
    const previousText = keyDeviceResetEl.textContent;
    setMidiInputArmed(false, "trinkey reset");
    browserIambicKeyer.panic("manual trinkey reset / all paddles released");
    resetCopyKeyInput("manual trinkey reset");
    keyDeviceResetEl.textContent = sendTrinkeyRelease("manual reset") ? "reset sent" : "no output";
    window.setTimeout(() => {
        keyDeviceResetEl.textContent = previousText;
        updateDeviceResetButton();
    }, 1200);
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
updateAudioDiagnostic();
updateDeviceResetButton();
connect();
