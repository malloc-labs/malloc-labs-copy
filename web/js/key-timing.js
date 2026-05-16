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
const rhythmReviewTabsEl = document.getElementById("key-rhythm-review-tabs");
const soundToggleEl = document.getElementById("key-sound-toggle");
const clearSentEl = document.getElementById("key-clear-sent");
const newSetEl = document.getElementById("key-new-set");
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
const copyImiEl = document.getElementById("copy-imi");
const copyHistoryEl = document.getElementById("copy-history");
const copyPositionLabelEl = document.getElementById("copy-position-label");
const copyHistoryToggleEl = document.getElementById("copy-history-toggle");
const copyHistoryArrowEl = document.getElementById("copy-history-arrow");
// Cadence-only collapsible toggles. Absent on the Freeplay page —
// every reference below must guard for null.
const sequenceToggleEl = document.getElementById("sequence-toggle");
const sequenceArrowEl = document.getElementById("sequence-arrow");
const keyPageActionsToggleEl = document.getElementById("key-page-actions-toggle");
const keyPageActionsArrowEl = document.getElementById("key-page-actions-arrow");
const keyPageActionsItemsEl = document.getElementById("key-page-actions-items");
const sentToggleEl = document.getElementById("sent-toggle");
const sentArrowEl = document.getElementById("sent-arrow");
const sentBodyEl = document.getElementById("key-sent-body");
const cadenceSpeakerEl = document.getElementById("cadence-speaker");

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
let lastSentEndedAt = null;
// One bucket of sent events per exercise (index-aligned to
// copyExercises). Filled live as sends arrive into the currently
// selected exercise; preserved across exercise selection so the
// learner can scroll the review and see prior attempts. Reset by
// the explicit "clear" button and when the engine ships a new
// exercise list.
let sentEventsByExercise = [];
let claimedSymbolSet = new Set();
// Left-Alt held state, tracked via event.code so we can scope the
// Cadence preview keybind to LeftAlt only (not RightAlt). Reset on blur
// because the matching keyup may never arrive if focus is lost.
let leftAltDown = false;
// IMI cue scheduling. lastNoteOffAt is stamped on every browser-MIDI
// note-off (not lastSentEndedAt — that only updates after a successful
// decode, so a runaway concat would let the cue flash while the learner
// is still actively keying). Cleared to null on the next note-on.
let lastNoteOffAt = null;
let imiCueTimerId = null;

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
    if (cadenceSpeakerEl) {
        cadenceSpeakerEl.dataset.state = soundEnabled ? "on" : "off";
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

function renderNewSetLabel() {
    if (!newSetEl) return;
    newSetEl.replaceChildren(makeAccelLabel("n", "ew"));
    newSetEl.title = "New exercise set (N)";
    newSetEl.setAttribute("aria-keyshortcuts", "N");
}

// Render the review as a tab bar (one tab per exercise) plus the
// selected exercise's baseline block. Each block carries one column per
// symbol (asymmetric green|amber|red zone group, fixed width per
// column), and any sent symbols overlaid beneath as an up-arrow + glyph
// at a continuous x-fraction. x=0 is a perfectly-timed leading gap
// relative to the column's *baseline-expected* gap (not the engine's
// runtime classification); x rises into amber/red as the gap stretches.
// dit_ms_expected from key-input-start is the source of truth for the
// ideal gap math.
function renderRhythmReview() {
    if (!rhythmReviewSymbolsEl || !rhythmReviewMetaEl) return;
    rhythmReviewSymbolsEl.replaceChildren();
    if (rhythmReviewTabsEl) rhythmReviewTabsEl.replaceChildren();

    const validIndices = copyExercises
        .map((ex, idx) => (ex && ex.length > 0 ? idx : -1))
        .filter((idx) => idx >= 0);
    rhythmReviewMetaEl.textContent =
        validIndices.length === 0
            ? "no exercises"
            : `${validIndices.length} ${validIndices.length === 1 ? "exercise" : "exercises"}`;

    if (validIndices.length === 0) return;

    if (!validIndices.includes(selectedReviewIndex)) {
        selectedReviewIndex = validIndices[0];
    }

    if (rhythmReviewTabsEl) {
        validIndices.forEach((exIdx, tabIdx) => {
            const exercise = copyExercises[exIdx];
            const tab = document.createElement("button");
            tab.type = "button";
            tab.className = "key-rhythm-review__tab";
            tab.role = "tab";
            tab.textContent = `${tabIdx + 1} / ${exercise}`;
            tab.title = exercise;
            const isSelected = exIdx === selectedReviewIndex;
            tab.setAttribute("aria-selected", String(isSelected));
            if (isSelected) tab.dataset.selected = "true";
            tab.addEventListener("click", () => {
                if (selectedReviewIndex === exIdx) return;
                selectedReviewIndex = exIdx;
                renderRhythmReview();
            });
            rhythmReviewTabsEl.appendChild(tab);
        });
    }

    const ditMs = Number(keyConfig && keyConfig.dit_ms_expected) || 60;
    const charGapMs = 3 * ditMs;
    const wordGapMs = 7 * ditMs;
    // Span over the ideal gap that the attempt marker can travel within
    // a column. Picked so that ~3x ideal lands at the right edge of red;
    // this is a perceptual mapping, not a hard tolerance.
    const X_SPAN_RATIO = 3.0;

    const exercise = copyExercises[selectedReviewIndex];
    const events = sentEventsByExercise[selectedReviewIndex] || [];
    rhythmReviewSymbolsEl.appendChild(
        buildExerciseBlock(
            exercise,
            selectedReviewIndex,
            events,
            charGapMs,
            wordGapMs,
            X_SPAN_RATIO,
        ),
    );
}

function buildExerciseBlock(exercise, exIdx, events, charGapMs, wordGapMs, X_SPAN_RATIO) {
    const block = document.createElement("section");
    block.className = "key-rhythm-baseline__exercise";
    block.setAttribute("aria-label", `Exercise ${exIdx + 1} baseline`);

    const labelEl = document.createElement("p");
    labelEl.className = "key-rhythm-baseline__exercise-label";
    labelEl.textContent = `Exercise ${exIdx + 1} / ${exercise}`;
    block.appendChild(labelEl);

    const colsEl = document.createElement("div");
    colsEl.className = "key-rhythm-baseline__cols";

    const charCols = [];
    const wordGapCols = [];
    // Per char column: the baseline-expected leading gap type that an
    // on-time send would produce. "none" for the first symbol; "word"
    // for the first symbol of each subsequent word; "character" for
    // in-word symbols. This is what we compare an actual send against —
    // *not* the engine's runtime classification, which only describes
    // what the user's pause actually crossed.
    const charColExpected = [];

    const buildZonesEl = () => {
        const zonesEl = document.createElement("div");
        zonesEl.className = "key-rhythm-baseline__zones";
        zonesEl.setAttribute("aria-hidden", "true");
        ["green", "amber", "red"].forEach((zone) => {
            const cell = document.createElement("span");
            cell.className = `key-rhythm-baseline__zone key-rhythm-baseline__zone--${zone}`;
            zonesEl.appendChild(cell);
        });
        return zonesEl;
    };

    const buildEmptyZonesEl = () => {
        const zonesEl = document.createElement("div");
        zonesEl.className = "key-rhythm-baseline__zones";
        return zonesEl;
    };

    const appendCharCol = (symbol) => {
        const col = document.createElement("div");
        col.className = "key-rhythm-baseline__col key-rhythm-baseline__col--char";

        const symEl = document.createElement("span");
        symEl.className = "key-rhythm-baseline__symbol";
        symEl.textContent = symbol;

        col.append(symEl, buildZonesEl());
        colsEl.appendChild(col);
        charCols.push(col);
    };

    const appendWordGapCol = () => {
        const col = document.createElement("div");
        col.className = "key-rhythm-baseline__col key-rhythm-baseline__col--word-gap";
        col.setAttribute("aria-hidden", "true");

        // Placeholder children carry the same vertical space as a char
        // column so the row stays aligned; nbsp keeps the symbol slot's
        // baseline, the empty zones div picks up its CSS height.
        const symEl = document.createElement("span");
        symEl.className = "key-rhythm-baseline__symbol";
        symEl.textContent = " ";

        col.append(symEl, buildEmptyZonesEl());
        colsEl.appendChild(col);
        wordGapCols.push(col);
    };

    const words = exercise.split(" ").filter((word) => word.length > 0);
    words.forEach((word, wordIdx) => {
        if (wordIdx > 0) appendWordGapCol();
        for (let i = 0; i < word.length; i++) {
            let expected;
            if (charCols.length === 0) expected = "none";
            else if (i === 0) expected = "word";
            else expected = "character";
            appendCharCol(word[i]);
            charColExpected.push(expected);
        }
    });

    // Segment events into attempt rows. Each event flagged
    // isAttemptStart begins a new row; subsequent events fill the row
    // left-to-right until the next start (or until the columns run
    // out). Events keyed before any attempt-start lands in an
    // implicit first row.
    if (charCols.length > 0) {
        const attempts = [];
        events.forEach((evt) => {
            if (evt.isAttemptStart || attempts.length === 0) {
                attempts.push([]);
            }
            attempts[attempts.length - 1].push(evt);
        });

        attempts.forEach((attempt, attemptIdx) => {
            for (let colIdx = 0; colIdx < charCols.length; colIdx++) {
                const col = charCols[colIdx];
                const attemptEl = document.createElement("div");
                attemptEl.className = "key-rhythm-baseline__attempt";
                const evt = attempt[colIdx];
                if (evt) {
                    const expected = charColExpected[colIdx];
                    const idealMs = expected === "word" ? wordGapMs : charGapMs;
                    const gapMs = Number(evt.leadingGapMs);
                    let xFrac = 0;
                    if (expected !== "none" && Number.isFinite(gapMs) && idealMs > 0) {
                        const overshootRatio = Math.max(0, (gapMs - idealMs) / idealMs);
                        xFrac = Math.min(1, overshootRatio / X_SPAN_RATIO);
                    }
                    const markerEl = document.createElement("div");
                    markerEl.className = "key-rhythm-baseline__attempt-marker";
                    markerEl.style.setProperty("--attempt-x", String(xFrac));
                    const arrowEl = document.createElement("span");
                    arrowEl.className = "key-rhythm-baseline__attempt-arrow";
                    arrowEl.setAttribute("aria-hidden", "true");
                    arrowEl.textContent = "↑";
                    const sentEl = document.createElement("span");
                    sentEl.className = "key-rhythm-baseline__attempt-symbol";
                    sentEl.textContent = evt.symbol;
                    markerEl.append(arrowEl, sentEl);
                    attemptEl.append(markerEl);
                }
                col.appendChild(attemptEl);
            }
            // After every second attempt (and not after the final one),
            // redraw the baseline bar so the next two attempts have a
            // fresh reference instead of stacking into a waterfall.
            const isLastAttempt = attemptIdx === attempts.length - 1;
            if ((attemptIdx + 1) % 2 === 0 && !isLastAttempt) {
                charCols.forEach((col) => col.appendChild(buildZonesEl()));
                wordGapCols.forEach((col) => col.appendChild(buildEmptyZonesEl()));
            }
        });
    }

    block.appendChild(colsEl);
    return block;
}

function setRhythmReviewExpanded(expanded) {
    if (!rhythmReviewToggleEl || !rhythmReviewArrowEl || !rhythmReviewBodyEl) return;
    rhythmReviewToggleEl.setAttribute("aria-expanded", String(expanded));
    rhythmReviewArrowEl.textContent = expanded ? "▼" : "▶";
    rhythmReviewBodyEl.hidden = !expanded;
}

function setCopyHistoryExpanded(expanded) {
    if (!copyHistoryToggleEl || !copyHistoryArrowEl || !copyHistoryEl) return;
    copyHistoryToggleEl.setAttribute("aria-expanded", String(expanded));
    copyHistoryArrowEl.textContent = expanded ? "▼" : "▶";
    copyHistoryEl.hidden = !expanded;
}

function setSequenceExpanded(expanded) {
    if (!sequenceToggleEl || !sequenceArrowEl || !sequenceRow) return;
    sequenceToggleEl.setAttribute("aria-expanded", String(expanded));
    sequenceArrowEl.textContent = expanded ? "▼" : "▶";
    sequenceRow.hidden = !expanded;
}

function setKeyPageActionsExpanded(expanded) {
    if (!keyPageActionsToggleEl || !keyPageActionsArrowEl || !keyPageActionsItemsEl) return;
    keyPageActionsToggleEl.setAttribute("aria-expanded", String(expanded));
    keyPageActionsArrowEl.textContent = expanded ? "▼" : "▶";
    keyPageActionsItemsEl.hidden = !expanded;
}

function setSentExpanded(expanded) {
    if (!sentToggleEl || !sentArrowEl || !sentBodyEl) return;
    sentToggleEl.setAttribute("aria-expanded", String(expanded));
    sentArrowEl.textContent = expanded ? "▼" : "▶";
    sentBodyEl.hidden = !expanded;
}

function toggleCopyHistory() {
    if (!copyHistoryToggleEl) return;
    const expanded = copyHistoryToggleEl.getAttribute("aria-expanded") === "true";
    setCopyHistoryExpanded(!expanded);
}

function toggleRhythmReview() {
    if (!rhythmReviewToggleEl) return;
    const expanded = rhythmReviewToggleEl.getAttribute("aria-expanded") === "true";
    setRhythmReviewExpanded(!expanded);
}

function toggleSequence() {
    if (!sequenceToggleEl) return;
    const expanded = sequenceToggleEl.getAttribute("aria-expanded") === "true";
    setSequenceExpanded(!expanded);
}

function toggleKeyPageActions() {
    if (!keyPageActionsToggleEl) return;
    const expanded = keyPageActionsToggleEl.getAttribute("aria-expanded") === "true";
    setKeyPageActionsExpanded(!expanded);
}

function toggleSent() {
    if (!sentToggleEl) return;
    const expanded = sentToggleEl.getAttribute("aria-expanded") === "true";
    setSentExpanded(!expanded);
}

function renderCopyHistoryToggleLabel() {
    const labelEl = document.getElementById("copy-history-label");
    if (!labelEl || !copyHistoryToggleEl) return;
    labelEl.replaceChildren(makeAccelLabel("e", ""));
    copyHistoryToggleEl.title = "Show/hide exercises (E)";
    copyHistoryToggleEl.setAttribute("aria-keyshortcuts", "E");
}

function renderRhythmReviewToggleLabel() {
    const labelEl = document.getElementById("key-rhythm-review-label");
    if (!labelEl || !rhythmReviewToggleEl) return;
    labelEl.replaceChildren(makeAccelLabel("r", ""));
    rhythmReviewToggleEl.title = "Review rhythm (R)";
    rhythmReviewToggleEl.setAttribute("aria-keyshortcuts", "R");
}

function renderSequenceToggleLabel() {
    const labelEl = document.getElementById("sequence-toggle-label");
    if (!labelEl || !sequenceToggleEl) return;
    labelEl.replaceChildren(makeAccelLabel("q", ""));
    sequenceToggleEl.title = "Show/hide sequence (Q)";
    sequenceToggleEl.setAttribute("aria-keyshortcuts", "Q");
}

function renderKeyPageActionsToggleLabel() {
    const labelEl = document.getElementById("key-page-actions-label");
    if (!labelEl || !keyPageActionsToggleEl) return;
    labelEl.replaceChildren(makeAccelLabel("t", ""));
    keyPageActionsToggleEl.title = "Show/hide top menu (T)";
    keyPageActionsToggleEl.setAttribute("aria-keyshortcuts", "T");
}

function renderSentToggleLabel() {
    const labelEl = document.getElementById("sent-toggle-label");
    if (!labelEl || !sentToggleEl) return;
    // Letters in "Sent" collide with M/S/E/N/T/C/R/Q so the accelerator
    // is bound to an out-of-word X. Render as ``Sent (x)``.
    labelEl.replaceChildren(
        document.createTextNode("Sent ("),
        makeAccelLabel("x", ""),
        document.createTextNode(")"),
    );
    sentToggleEl.title = "Show/hide sent symbols (X)";
    sentToggleEl.setAttribute("aria-keyshortcuts", "X");
}

function updateCopyPositionLabel() {
    if (!copyPositionLabelEl) return;
    const total = copyExercises.length;
    if (total === 0) {
        copyPositionLabelEl.textContent = "Exercise sequence:";
        return;
    }
    const position = Math.min(selectedCopyIndex + 1, total);
    copyPositionLabelEl.textContent = `Exercise sequence ${position}/${total}:`;
}

function clearSentSymbols() {
    sentSymbolEl.textContent = "—";
    sentHistoryEl.replaceChildren();
    lastSentEndedAt = null;
    // Intentionally do NOT touch sentEventsByExercise or re-render the
    // review — clear is scoped to the Sent line so the review section
    // preserves prior attempts across clears.
    copyProgress = 0;
    clearImiCue();
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
        lastNoteOffAt = null;
        clearImiCue();
        pendingRawOns.push({ kind, note: event.note, timestamp: Number(event.timestamp) });
        sidetone.keyDown(event.note);
    } else {
        sidetone.keyUp(event.note);
        lastNoteOffAt = performance.now();
        refreshImiCue();
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
    // A fresh set discards any in-flight state; collapse every
    // disclosure so the page returns to its default quiet layout.
    setSentExpanded(false);
    setSequenceExpanded(false);
    setKeyPageActionsExpanded(false);
    setCopyHistoryExpanded(false);
    setRhythmReviewExpanded(false);
}

let selectedCopyIndex = 0;
// Which exercise's baseline block the review section shows. Tracks the
// current copy exercise by default; tab clicks override it without
// affecting copy progress.
let selectedReviewIndex = 0;
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

// Show "IMI - Repeat; Say Again" once the learner has been silent for
// word_gap_seconds with an in-flight attempt (copyProgress > 0). Word
// gap is the threshold rather than character gap so the cue never
// flickers during normal inter-character pauses inside an exercise.
// Full reset — used by session events (clear, exercise switch,
// completion) so the cue doesn't reappear after the context has
// moved on. Resets lastNoteOffAt so a stale note-off can't trigger
// the cue in the new context.
function clearImiCue() {
    if (imiCueTimerId !== null) {
        clearTimeout(imiCueTimerId);
        imiCueTimerId = null;
    }
    lastNoteOffAt = null;
    if (copyImiEl) copyImiEl.hidden = true;
}

// Idempotent — recomputes the cue's pending-vs-visible state from
// current lastNoteOffAt. Called from note-off and whenever copyProgress
// changes via sent-symbol, so the cue tracks the actual silence window
// rather than the moment of any single event. Intentionally does not
// gate on copyProgress: after a runaway concat the decoder emits `?`
// and noteCopySymbolForProgress resets progress to 0, but the learner
// still needs the cue at that point — they were keying, they paused,
// they want to try again.
function refreshImiCue() {
    if (imiCueTimerId !== null) {
        clearTimeout(imiCueTimerId);
        imiCueTimerId = null;
    }
    if (!copyImiEl) return;
    if (expectedCopySteps.length === 0 || lastNoteOffAt === null) {
        copyImiEl.hidden = true;
        return;
    }
    const ditMs = Number(keyConfig?.dit_ms_expected) || 60;
    const wordGapMs = 7 * ditMs;
    const elapsed = performance.now() - lastNoteOffAt;
    if (elapsed >= wordGapMs) {
        copyImiEl.hidden = false;
        return;
    }
    copyImiEl.hidden = true;
    imiCueTimerId = window.setTimeout(() => {
        imiCueTimerId = null;
        if (expectedCopySteps.length === 0 || lastNoteOffAt === null) return;
        copyImiEl.hidden = false;
    }, wordGapMs - elapsed);
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
            // Advance to the next exercise in the current set if any.
            // On the final exercise we deliberately stop — the learner
            // presses "new" (or N) to request a fresh set, which keeps
            // the last review intact until they decide to move on.
            if (selectedCopyIndex + 1 < copyExercises.length) {
                selectCopyExercise(selectedCopyIndex + 1);
            } else {
                sentSymbolEl.textContent = "Completed";
                // Auto-reveal the Sent history so the learner can scan
                // the final set of attempts without first hitting X.
                setSentExpanded(true);
                clearImiCue();
            }
        }
        refreshImiCue();
        return;
    }

    // Mismatch — fall back to step 0. If this symbol matches step 0's symbol,
    // count the current input as the start of a fresh attempt.
    copyProgress = symbol === expectedCopySteps[0].symbol ? 1 : 0;
    refreshImiCue();
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
    selectedReviewIndex = 0;
    copyExercises = exercises;
    sentEventsByExercise = exercises.map(() => []);
    updateExpectedCopySteps();
    clearImiCue();
    if (exercises.length === 0) {
        copySymbolEl.textContent = "—";
        updateCopyPositionLabel();
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
    updateCopyPositionLabel();
    renderRhythmReview();
}

function selectCopyExercise(idx) {
    if (!copyHistoryEl || !copySymbolEl) return false;
    const items = copyHistoryEl.querySelectorAll(".key-copy-history__item");
    if (idx < 0 || idx >= items.length) return false;
    selectedCopyIndex = idx;
    selectedReviewIndex = idx;
    items.forEach((item, i) => {
        if (i === idx) item.dataset.selected = "true";
        else delete item.dataset.selected;
    });
    copySymbolEl.textContent = items[idx].dataset.exercise || "";
    updateExpectedCopySteps();
    clearImiCue();
    updateCopyPositionLabel();
    renderRhythmReview();
    return true;
}

// Predict whether the incoming event should start a new attempt row,
// using the same step-walking vocabulary as noteCopySymbolForProgress
// but called *before* that function mutates copyProgress. A new row
// is begun only when the event matches step 0 of the exercise — either
// from a clean state (copyProgress === 0) or as a mid-stream restart
// where the user re-keys the exercise's first symbol while we'd been
// expecting a later step. Junk symbols that don't match step 0 append
// to the current row instead of fragmenting the display.
function isAttemptStartForEvent(symbol, leadingGap) {
    if (expectedCopySteps.length === 0) return true;
    const stepZero = expectedCopySteps[0];
    if (!stepZero || symbol !== stepZero.symbol) return false;
    if (copyProgress === 0) return true;
    // Mid-stream: only a restart if the current expected step isn't
    // also satisfied by this event (e.g., MUM at progress=2 expects M
    // and the user keys M — that's the legitimate finish, not a
    // restart).
    const expected = expectedCopySteps[copyProgress];
    const continuesCurrentStep =
        expected && symbol === expected.symbol && leadingGap === expected.leading;
    return !continuesCurrentStep;
}

function clearCopyExercises() {
    if (!copyHistoryEl || !copySymbolEl) return;
    copySymbolEl.textContent = "—";
    copyHistoryEl.replaceChildren();
    selectedCopyIndex = 0;
    selectedReviewIndex = 0;
    copyExercises = [];
    sentEventsByExercise = [];
    updateExpectedCopySteps();
    clearImiCue();
    updateCopyPositionLabel();
    renderRhythmReview();
}

function renderSentSymbol(event) {
    const symbol = event.symbol || "?";
    const startedAt = Number(event.started_at);
    const endedAt = Number(event.ended_at);
    const leadingGapMs = Number.isFinite(startedAt) && Number.isFinite(lastSentEndedAt)
        ? Math.max(0, (startedAt - lastSentEndedAt) * 1000)
        : null;

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

    if (Number.isFinite(endedAt)) {
        lastSentEndedAt = endedAt;
    }
    const bucket = sentEventsByExercise[selectedCopyIndex];
    if (bucket) {
        bucket.push({
            symbol,
            leadingGap: event.leading_gap || "none",
            leadingGapMs,
            // Computed against copyProgress *before* noteCopySymbolForProgress
            // runs below — true on the event that begins a fresh walk through
            // the exercise (progress was 0) or on a mid-stream restart where
            // the symbol matches step 0 after a mismatch. The renderer
            // segments the bucket into rows on these boundaries.
            isAttemptStart: isAttemptStartForEvent(symbol, event.leading_gap || "none"),
        });
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
if (newSetEl) newSetEl.addEventListener("click", requestCopyExercises);
if (rhythmReviewToggleEl) {
    rhythmReviewToggleEl.addEventListener("click", () => {
        const expanded = rhythmReviewToggleEl.getAttribute("aria-expanded") === "true";
        setRhythmReviewExpanded(!expanded);
    });
}
if (copyHistoryToggleEl) {
    copyHistoryToggleEl.addEventListener("click", () => {
        const expanded = copyHistoryToggleEl.getAttribute("aria-expanded") === "true";
        setCopyHistoryExpanded(!expanded);
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
    } else if (key === "n") {
        event.preventDefault();
        requestCopyExercises();
    } else if (key === "e") {
        event.preventDefault();
        toggleCopyHistory();
    } else if (key === "r") {
        event.preventDefault();
        toggleRhythmReview();
    } else if (key === "q") {
        event.preventDefault();
        toggleSequence();
    } else if (key === "t") {
        event.preventDefault();
        toggleKeyPageActions();
    } else if (key === "x") {
        event.preventDefault();
        toggleSent();
    } else if (/^[1-9]$/.test(key)) {
        if (selectCopyExercise(parseInt(key, 10) - 1)) {
            event.preventDefault();
        }
    }
});
renderClearSentLabel();
renderNewSetLabel();
renderCopyHistoryToggleLabel();
renderRhythmReviewToggleLabel();
renderSequenceToggleLabel();
renderKeyPageActionsToggleLabel();
renderSentToggleLabel();
renderRhythmReview();
updateAudioDiagnostic();
connect();
