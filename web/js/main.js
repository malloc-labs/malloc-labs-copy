// Copy — Koch Exercise UI.
//
// One WebSocket to the engine. The page manages the claimed Koch symbol
// set, starts/stops listening sessions, and keeps truth disclosure locked
// until session-end. No framework, no build step (spec §12).

import { PATTERNS, spokenMorsePattern } from "./morse-display.js";

const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
const wsUrl = `${wsProtocol}//${location.host}/ws`;

const statusEl     = document.querySelector(".status");
const eventsEl     = document.getElementById("events");
const answersEl    = document.getElementById("answers");
const startBtn     = document.getElementById("start");
const countdownEl  = document.getElementById("countdown");
const saveBtn      = document.getElementById("save-answers");
const sequenceRow  = document.getElementById("sequence-row");
const primedEl     = document.getElementById("primed");

// Pre-start countdown — gives the learner a moment to settle before
// audio begins. Cancellable while ticking by clicking Start (which
// reads as "Cancel" during the count) or pressing the S keybind.
const COUNTDOWN_SECONDS = 5;
let countdownTimer = null;

// Canonical Koch order — mirrors KOCH_ORDER in patterns.py.
// This is the single source of truth for the UI sequence display.
const KOCH_ORDER = [
    "K", "M", "U", "R", "E", "S", "N", "A", "P", "T",
    "L", "W", "I", ".", "J", "Z", "=", "F", "O", "Y",
    ",", "V", "G", "5", "/", "Q", "9", "2", "H", "3",
    "8", "B", "?", "4", "7", "C", "1", "D", "6", "0", "X",
];

// K and M are the permanent starting pair — cannot be unclaimed.
const PERMANENT = new Set(["K", "M"]);

// Latest claimed-symbols payload from the engine.
let claimedState     = { symbols: [], suggested_next: null };
// Mirror of claimed symbols as a Set for O(1) lookup by the
// Left-Alt preview handler. Refreshed inside renderSequence.
let claimedSymbolSet = new Set();
// Session shape: the engine sends the full ordered exercise list on
// session-start. The UI holds it locally so it can label the post-session
// timeline once truth unlocks; we never display the strings while the
// learner is listening.
let currentExercises = [];
let currentExerciseIndex = 0;
const EXERCISE_COUNT = 5;
let sessionActive   = false;
let sessionStartedAtMs = null;

let socket = null;

// ─── Koch sequence row ────────────────────────────────────────────────────────
// Renders the full 41-symbol sequence as clickable token buttons.
// Each token carries data-state: "claimed" | "next" | "available"
// Clicking a claimed token unclaims it (unless it's K or M).
// Clicking an available or next token claims it.

function buildSequenceRow() {
    sequenceRow.replaceChildren();
    KOCH_ORDER.forEach((sym) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = sym;
        btn.dataset.symbol = sym;
        btn.dataset.state = "available";
        btn.setAttribute("role", "listitem");
        btn.classList.add("seq-token");
        btn.addEventListener("click", () => onTokenClick(sym));
        sequenceRow.appendChild(btn);
    });
}

function renderSequence(state) {
    claimedState = state;
    const claimedSet = new Set(state.symbols);
    claimedSymbolSet = claimedSet;
    // Saved-evidence readiness for the next-symbol nudge. Painted as
    // a row-level attribute so CSS toggles the box on the "next"
    // token without per-token logic. Server defaults to false on
    // insufficient evidence, and now also holds back under the
    // per-claimed-set wall-clock floor (the soft gate — focused
    // listening for a few minutes can satisfy the evidence analysis
    // long before any meaningful contact time has accumulated).
    //
    // When the gate is closed, the suggested-next symbol is rendered
    // the same as any other unclaimed symbol — no distinct colour,
    // no box. The learner can still click to claim it; we are only
    // suppressing the implication that they should.
    sequenceRow.dataset.ready = state.ready_for_next ? "true" : "false";
    const next = state.ready_for_next ? state.suggested_next : null;

    KOCH_ORDER.forEach((sym) => {
        const btn = sequenceRow.querySelector(`[data-symbol="${CSS.escape(sym)}"]`);
        if (!btn) return;

        if (claimedSet.has(sym)) {
            btn.dataset.state = "claimed";
            btn.disabled = PERMANENT.has(sym); // K and M are non-interactive
            btn.title = PERMANENT.has(sym)
                ? `${sym} — starting pair, always claimed`
                : `${sym} — claimed (click to remove)`;
        } else if (sym === next) {
            btn.dataset.state = "next";
            btn.disabled = false;
            btn.title = `${sym} — next in sequence (click to claim)`;
        } else {
            btn.dataset.state = "available";
            btn.disabled = false;
            btn.title = `${sym} — click to claim`;
        }
    });

    renderPrimed();
}

function onTokenClick(sym) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    if (sessionActive) return; // no claim changes mid-session
    const claimedSet = new Set(claimedState.symbols);
    if (claimedSet.has(sym)) {
        if (PERMANENT.has(sym)) return; // K and M cannot be unclaimed
        socket.send(JSON.stringify({ action: "unclaim-symbol", symbol: sym }));
    } else {
        socket.send(JSON.stringify({ action: "claim-symbol", symbol: sym }));
    }
}

function renderPrimed() {
    if (!claimedState.symbols.length) {
        primedEl.textContent = "Primed: nothing — claim a symbol first";
        return;
    }
    primedEl.textContent =
        `Primed: ${EXERCISE_COUNT} exercises of ${claimedState.symbols.join(", ")}`;
}

// ─── Timeline disclosure ──────────────────────────────────────────────────────

const toggleBtn    = document.querySelector(".timeline-toggle");
const timelineBody = document.querySelector(".timeline-body");

function setTimelineOpen(open) {
    const arrow = toggleBtn.querySelector(".timeline-arrow");
    if (open) {
        timelineBody.hidden = false;
        arrow.textContent   = "▼";
        toggleBtn.setAttribute("aria-expanded", "true");
    } else {
        timelineBody.hidden = true;
        arrow.textContent   = "▶";
        toggleBtn.setAttribute("aria-expanded", "false");
    }
}

function setTimelineLocked(locked) {
    if (locked) {
        toggleBtn.setAttribute("aria-disabled", "true");
        toggleBtn.classList.add("timeline-toggle--locked");
    } else {
        toggleBtn.removeAttribute("aria-disabled");
        toggleBtn.classList.remove("timeline-toggle--locked");
    }
}

toggleBtn.addEventListener("click", () => {
    if (toggleBtn.getAttribute("aria-disabled") === "true") return;
    const isOpen = toggleBtn.getAttribute("aria-expanded") === "true";
    setTimelineOpen(!isOpen);
});

setTimelineOpen(false);
setTimelineLocked(true);

// ─── Truth disclosure tabs ────────────────────────────────────────────────────
// Answers (Tab 1) is the learner's input panel; Truth (Tab 2) is the rendered
// exercise list. Both live inside the collapsible disclosure, so neither is
// reachable until session-end unlocks .timeline-toggle.

const tabButtons = document.querySelectorAll(".timeline-tab");
const tabPanels  = {
    answers: document.getElementById("timeline-panel-answers"),
    truth:   document.getElementById("timeline-panel-truth"),
};

function setActiveTab(name) {
    tabButtons.forEach((btn) => {
        const selected = btn.dataset.tab === name;
        btn.dataset.selected   = selected ? "true" : "false";
        btn.setAttribute("aria-selected", selected ? "true" : "false");
    });
    Object.entries(tabPanels).forEach(([key, panel]) => {
        panel.hidden = key !== name;
    });
}

tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => setActiveTab(btn.dataset.tab));
});

setActiveTab("answers");

function buildAnswerInputs(exercises) {
    answersEl.replaceChildren();
    exercises.forEach((_, idx) => {
        const li = document.createElement("li");
        li.className = "answer-row";

        const label = document.createElement("label");
        const inputId = `answer-${idx + 1}`;
        label.htmlFor = inputId;
        label.className = "answer-row__label";
        label.textContent = `Exercise ${idx + 1}:`;

        const input = document.createElement("input");
        input.type = "text";
        input.id = inputId;
        input.className = "answer-row__input";
        input.autocomplete = "off";
        input.autocapitalize = "characters";
        input.spellcheck = false;
        input.disabled = true;
        // Any edit after a successful save returns Save to the
        // unsaved "Save" affordance so the learner can write the
        // updated answers back to the record.
        input.addEventListener("input", () => {
            const start = input.selectionStart;
            const end = input.selectionEnd;
            const upper = input.value.toUpperCase();
            if (upper !== input.value) {
                input.value = upper;
                input.setSelectionRange(start, end);
            }
            if (saveBtn.dataset.state === "saved") setSaveState("ready");
        });

        li.append(label, input);
        answersEl.appendChild(li);
    });
}

function setAnswerInputsEnabled(enabled) {
    answersEl.querySelectorAll(".answer-row__input").forEach((input) => {
        input.disabled = !enabled;
    });
}

function collectAnswers() {
    return Array.from(answersEl.querySelectorAll(".answer-row__input"), (input) => input.value);
}

// Save button state machine: locked (session in flight / no review yet) →
// ready (review unlocked, learner can save) → saved (server ack received,
// no edits since) → ready (any input edit returns to "Save").
function setSaveState(state) {
    saveBtn.dataset.state = state;
    if (state === "locked") {
        saveBtn.disabled    = true;
        saveBtn.textContent = "Save";
    } else if (state === "ready") {
        saveBtn.disabled    = false;
        saveBtn.textContent = "Save";
    } else if (state === "saved") {
        saveBtn.disabled    = true;
        saveBtn.textContent = "Saved";
    }
}

setSaveState("locked");

// ─── Status ───────────────────────────────────────────────────────────────────

function setStatus(state, text) {
    statusEl.dataset.status = state;
    statusEl.textContent    = text;
}

// ─── Event rendering ──────────────────────────────────────────────────────────

function formatClockTime(secondsAfterSessionStart) {
    const baseMs = sessionStartedAtMs ?? Date.now();
    const timestamp = new Date(baseMs + Math.max(0, secondsAfterSessionStart) * 1000);
    return [timestamp.getHours(), timestamp.getMinutes(), timestamp.getSeconds()]
        .map((part) => String(part).padStart(2, "0"))
        .join(":");
}

function formatSymbolReview(event) {
    const pattern = PATTERNS[event.symbol];
    const spoken = pattern ? ` ${spokenMorsePattern(pattern)}` : "";
    return `${formatClockTime(event.t_on)} ${event.symbol}${spoken}`;
}

function setSequenceTokenPlaying(symbol, playing) {
    sequenceRow.querySelectorAll("[data-playing]").forEach((el) => {
        delete el.dataset.playing;
    });
    if (!playing || !symbol) return;
    const token = sequenceRow.querySelector(`[data-symbol="${CSS.escape(symbol)}"]`);
    if (token) token.dataset.playing = "true";
}

function appendEvent(event) {
    if (event.type === "claimed-symbols") {
        renderSequence(event);
        return;
    }
    if (event.type === "morse-repeat-start") {
        setSequenceTokenPlaying(event.symbol, true);
        return;
    }
    if (event.type === "morse-repeat-end") {
        setSequenceTokenPlaying(event.symbol, false);
        return;
    }

    const li = document.createElement("li");

    if (event.type === "symbol") {
        // Open a new exercise frame whenever the engine advances. The
        // header itself stays hidden behind the timeline lock until
        // session-end — see setTimelineLocked.
        if (event.exercise_index !== currentExerciseIndex) {
            if (currentExerciseIndex !== 0) {
                const divider = document.createElement("li");
                divider.dataset.kind = "exercise-divider";
                divider.appendChild(document.createElement("hr"));
                eventsEl.appendChild(divider);
            }
            currentExerciseIndex = event.exercise_index;
            const header = document.createElement("li");
            header.dataset.kind = "exercise-header";
            const exerciseString = currentExercises[event.exercise_index - 1] || "";
            header.textContent = `Exercise ${event.exercise_index}: ${exerciseString}`;
            eventsEl.appendChild(header);
            primedEl.textContent =
                `Exercise ${currentExerciseIndex} of ${currentExercises.length}`;
        }
        li.textContent  = formatSymbolReview(event);
        li.dataset.kind = "symbol";
        li.dataset.exerciseIndex = String(event.exercise_index);
        li.dataset.wordIndex = String(event.word_index);

    } else if (event.type === "session-start") {
        currentExercises = Array.isArray(event.exercises) ? event.exercises : [];
        currentExerciseIndex = 0;
        sessionActive   = true;
        sessionStartedAtMs = Date.now();
        setStartButtonMode("active");

        const meta = toggleBtn.querySelector(".timeline-meta");
        meta.textContent =
            `seed ${event.seed} · ${currentExercises.length} exercises`;

        setTimelineLocked(true);
        setTimelineOpen(false);
        setActiveTab("answers");
        eventsEl.replaceChildren();
        buildAnswerInputs(currentExercises);
        setSaveState("locked");
        primedEl.textContent = `Exercise — of ${currentExercises.length}`;
        return;

    } else if (event.type === "session-end") {
        sessionActive     = false;
        li.textContent    = "■ end";
        li.dataset.kind   = "end";
        setStartButtonMode("idle");
        sessionStartedAtMs = null;
        setTimelineLocked(false);
        setAnswerInputsEnabled(true);
        // Only enable Save when there was actually a session to save
        // answers for. A session-end with no exercises means abort
        // before session-start — nothing to write.
        setSaveState(currentExercises.length > 0 ? "ready" : "locked");
        renderPrimed();

    } else if (event.type === "koch-answers-saved") {
        setSaveState("saved");
        return;

    } else if (event.type === "error") {
        const detail = event.detail ? `: ${event.detail}`
                     : event.symbol ? `: ${event.symbol}`
                     : "";
        li.textContent    = `! ${event.reason}${detail}`;
        li.dataset.kind   = "error";
        // Session-related errors retire the in-flight state; an
        // answers-save error leaves sessionActive untouched so the
        // learner can fix the typed answers and retry.
        const ANSWERS_ERRORS = new Set([
            "no-pending-koch-record",
            "invalid-answers",
            "answers-length-mismatch",
            "pending-koch-record-missing",
        ]);
        if (ANSWERS_ERRORS.has(event.reason)) {
            setSaveState("ready");
        } else {
            setStartButtonMode("idle");
            sessionActive     = false;
            sessionStartedAtMs = null;
            setTimelineLocked(false);
        }

    } else {
        li.textContent = JSON.stringify(event);
    }

    eventsEl.appendChild(li);
}

// ─── WebSocket ────────────────────────────────────────────────────────────────

function connect() {
    socket = new WebSocket(wsUrl);

    socket.addEventListener("open", () => {
        setStatus("connected", "connected");
        setStartButtonMode("idle");
    });

    socket.addEventListener("message", (msg) => {
        let event;
        try {
            event = JSON.parse(msg.data);
        } catch {
            event = { type: "error", reason: "invalid-json-from-engine" };
        }
        appendEvent(event);
    });

    socket.addEventListener("close", () => {
        setStatus("disconnected", "disconnected");
        clearCountdown();
        startBtn.disabled = true;
        sessionActive     = false;
        sessionStartedAtMs = null;
        setSaveState("locked");
        setTimelineLocked(false);
    });

    socket.addEventListener("error", () => {
        setStatus("error", "connection error");
    });
}

// ─── Controls ─────────────────────────────────────────────────────────────────

// Start is a three-state toggle: idle → begin a 5-second pre-start
// countdown; counting → cancel the countdown and return to idle;
// active → abort the in-flight session. ``data-mode`` mirrors the
// state for CSS hooks without re-reading the button text.
function setStartButtonMode(mode) {
    startBtn.dataset.mode = mode;
    if (mode === "idle") {
        clearCountdown();
        startBtn.disabled  = !socket || socket.readyState !== WebSocket.OPEN;
        // <u>S</u>tart — keybind hint matches aria-keyshortcuts="S".
        startBtn.innerHTML = "<u>S</u>tart";
    } else if (mode === "counting") {
        startBtn.disabled    = false;
        startBtn.textContent = "Cancel";
    } else if (mode === "active") {
        clearCountdown();
        startBtn.disabled    = false;
        startBtn.textContent = "Abort";
    }
}

function clearCountdown() {
    if (countdownTimer !== null) {
        clearInterval(countdownTimer);
        countdownTimer = null;
    }
    countdownEl.hidden = true;
    countdownEl.textContent = "";
}

function beginCountdownThenStart() {
    let remaining = COUNTDOWN_SECONDS;
    countdownEl.hidden = false;
    countdownEl.textContent = String(remaining);
    setStartButtonMode("counting");
    resetReviewSection();

    countdownTimer = setInterval(() => {
        remaining -= 1;
        if (remaining > 0) {
            countdownEl.textContent = String(remaining);
            return;
        }
        clearInterval(countdownTimer);
        countdownTimer = null;
        countdownEl.hidden = true;
        countdownEl.textContent = "";
        if (!socket || socket.readyState !== WebSocket.OPEN) {
            setStartButtonMode("idle");
            return;
        }
        socket.send(JSON.stringify({ action: "start" }));
        startBtn.disabled = true;
    }, 1000);
}

function resetReviewSection() {
    // A new Start (or its first ``session-start``) wipes the previous
    // review: timeline meta, events list, answer inputs, save state.
    // Discarding unsaved answers is intentional — see the design
    // discussion that produced this flow.
    eventsEl.replaceChildren();
    answersEl.replaceChildren();
    const meta = toggleBtn.querySelector(".timeline-meta");
    meta.textContent = "—";
    currentExercises = [];
    currentExerciseIndex = 0;
    setActiveTab("answers");
    setTimelineOpen(false);
    setTimelineLocked(true);
    setSaveState("locked");
}

startBtn.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const mode = startBtn.dataset.mode;
    if (mode === "active") {
        // Abort path: cancel the in-flight session. The engine will
        // emit session-end, which flips the button back to "Start".
        socket.send(JSON.stringify({ action: "stop" }));
        startBtn.disabled = true;
        return;
    }
    if (mode === "counting") {
        // Cancel the pre-start countdown — no engine action yet.
        setStartButtonMode("idle");
        return;
    }
    // Idle path: wipe review state and run the pre-start countdown.
    beginCountdownThenStart();
});

saveBtn.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    if (saveBtn.dataset.state !== "ready") return;
    socket.send(JSON.stringify({ action: "save-koch-answers", answers: collectAnswers() }));
});

// ─── Start keybind (S) ────────────────────────────────────────────────────────
// Mirrors aria-keyshortcuts="S" on the Start button. Skips when a
// modifier is held or focus is in an editable element so it never
// fights a real text field. Whatever mode the button is in, this just
// re-routes through its click handler.

window.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
    }
    if (event.key.toLowerCase() !== "s") return;
    if (startBtn.disabled) return;
    event.preventDefault();
    startBtn.click();
});

// ─── Symbol preview (Left Alt + key) ──────────────────────────────────────────
// Plays a claimed symbol's bare Morse three times through the engine so the
// learner can refresh their ear between sessions. ``event.code`` is used
// because Option+letter on macOS substitutes the character in ``event.key``;
// LeftAlt is tracked separately because ``event.altKey`` does not
// distinguish left from right.

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

let leftAltDown = false;

window.addEventListener("keydown", (event) => {
    if (event.code === "AltLeft") {
        leftAltDown = true;
        return;
    }
    if (!leftAltDown || !event.altKey) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    // Preview audio would collide with in-flight session playback.
    if (sessionActive) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
    }
    const symbol = symbolForPreviewCode(event.code, event.shiftKey);
    if (!symbol) return;
    // Only claimed symbols are previewable. The fixed DE listening
    // anchor (spec §2.5) is deliberately ear-only and not available
    // for active review here.
    if (!claimedSymbolSet.has(symbol)) return;
    event.preventDefault();
    if (event.repeat) return;
    socket.send(JSON.stringify({ action: "play-morse-repeat", symbol }));
});

window.addEventListener("keyup", (event) => {
    if (event.code === "AltLeft") {
        leftAltDown = false;
    }
});

window.addEventListener("blur", () => {
    leftAltDown = false;
});

// ─── Init ─────────────────────────────────────────────────────────────────────

buildSequenceRow();
connect();
