// Copy — Koch Exercise UI.
//
// One WebSocket to the engine. The page manages the claimed Koch symbol
// set, starts/stops listening sessions, and keeps truth disclosure locked
// until session-end. No framework, no build step (spec §12).

import { PATTERNS, spokenMorsePattern } from "./morse-display.js";
import {
    clearCountdown as clearCountdownCore,
    connectKoch,
    installClaimHandlers,
    renderSequence as renderKochSequence,
    setSequenceTokenPlaying,
    startCountdown,
} from "./koch-core.js";

const eventsEl     = document.getElementById("events");
const answersEl    = document.getElementById("answers");
const startBtn     = document.getElementById("start");
const countdownEl  = document.getElementById("countdown");
const saveBtn      = document.getElementById("save-answers");
const sequenceRow  = document.getElementById("sequence-row");
const primedEl     = document.getElementById("primed");
const primedTextEl = document.getElementById("primed-text");
const primedSetEl  = document.getElementById("primed-set");

// Pre-start countdown — gives the learner a moment to settle before
// audio begins. Cancellable while ticking by clicking Start (which
// reads as "Cancel" during the count) or pressing the S keybind.
const COUNTDOWN_SECONDS = 5;
let countdownTimer = null;

// Latest claimed-symbols payload from the engine.
let claimedState     = { symbols: [], suggested_next: null, set_is_fresh: true };
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
const SET_SIZE = 8;
let currentSetSession = 0;
let currentKochGears = [];
let currentKochWarmUp = false;
let sessionActive   = false;
let sessionStartedAtMs = null;

let socket = null;

// ─── Koch sequence row ────────────────────────────────────────────────────────

function renderSequence(state) {
    claimedState = state;
    claimedSymbolSet = renderKochSequence(sequenceRow, state);
    renderPrimed();
}

function renderPrimed() {
    if (!claimedState.symbols.length) {
        primedTextEl.textContent = "Primed: nothing — claim a symbol first";
        primedSetEl.textContent = "";
        return;
    }
    primedTextEl.textContent =
        `Primed: ${EXERCISE_COUNT} exercises of ${claimedState.symbols.join(", ")}`;
    primedSetEl.textContent = kochSetNotice();
}

function kochSetNotice() {
    if (currentSetSession <= 0) return "";
    const mode = kochModeLabel(currentKochGears, currentKochWarmUp);
    return mode
        ? `Set ${currentSetSession} of ${SET_SIZE} · ${mode}`
        : `Set ${currentSetSession} of ${SET_SIZE}`;
}

function kochModeLabel(gears, warmUp) {
    if (warmUp) return "Warm-up: 2-symbol words";
    const validGears = (Array.isArray(gears) ? gears : [])
        .filter((gear) => Number.isInteger(gear) && gear >= 0);
    if (!validGears.length) return "Koch exercises: 1-3 words, 1-3 symbols each";
    const uniqueGears = [...new Set(validGears)].sort((a, b) => a - b);
    const content = "1-3 words, 1-3 symbols each";
    if (uniqueGears.length === 1) {
        return `${kochGearLabel(uniqueGears[0])}: ${content}`;
    }
    return `Mixed gears ${uniqueGears.join(", ")}: ${content}`;
}

function kochGearLabel(gear) {
    if (gear <= 0) return "Gear 0";
    if (gear === 1) return "Gear 1, upper-band copy";
    if (gear === 2) return "Gear 2, next-band copy";
    if (gear === 3) return "Gear 3, scaffold-break copy";
    return `Gear ${gear}`;
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
    // Two-column table (Answer | Sent) with a leading row-header showing
    // the exercise number. The Sent column starts empty; it's filled
    // post-save by revealSent() once the engine acks koch-answers-saved.
    answersEl.replaceChildren();

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    const cornerTh = document.createElement("th");
    cornerTh.scope = "col";
    cornerTh.className = "answers-table__corner";
    const answerTh = document.createElement("th");
    answerTh.scope = "col";
    answerTh.textContent = "Answer";
    const sentTh = document.createElement("th");
    sentTh.scope = "col";
    sentTh.textContent = "Sent";
    headerRow.append(cornerTh, answerTh, sentTh);
    thead.appendChild(headerRow);

    const tbody = document.createElement("tbody");
    exercises.forEach((_, idx) => {
        const tr = document.createElement("tr");
        tr.className = "answer-row";

        const rowHeader = document.createElement("th");
        rowHeader.scope = "row";
        rowHeader.className = "answer-row__label";
        const inputId = `answer-${idx + 1}`;
        const labelLink = document.createElement("label");
        labelLink.htmlFor = inputId;
        labelLink.textContent = String(idx + 1);
        rowHeader.appendChild(labelLink);

        const answerCell = document.createElement("td");
        answerCell.className = "answer-row__cell";
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
        answerCell.appendChild(input);

        const sentCell = document.createElement("td");
        sentCell.className = "answer-row__sent";
        sentCell.dataset.sentFor = String(idx);

        tr.append(rowHeader, answerCell, sentCell);
        tbody.appendChild(tr);
    });

    answersEl.append(thead, tbody);
}

function revealSentColumn() {
    answersEl.querySelectorAll("[data-sent-for]").forEach((cell) => {
        const idx = Number(cell.dataset.sentFor);
        const sent = currentExercises[idx] || "";
        cell.textContent = sent;
        const input = document.getElementById(`answer-${idx + 1}`);
        const answer = (input ? input.value : "").trim().toUpperCase();
        const isCorrect = answer === sent.trim().toUpperCase();
        cell.dataset.correct = isCorrect ? "true" : "false";
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

function appendEvent(event) {
    if (event.type === "claimed-symbols") {
        currentSetSession = Number.isInteger(event.koch_set_session)
            ? event.koch_set_session
            : currentSetSession;
        currentKochGears = Array.isArray(event.koch_gears)
            ? event.koch_gears
            : currentKochGears;
        currentKochWarmUp = event.koch_warm_up === true;
        renderSequence(event);
        return;
    }
    if (event.type === "morse-repeat-start") {
        setSequenceTokenPlaying(sequenceRow, event.symbol, true);
        return;
    }
    if (event.type === "morse-repeat-end") {
        setSequenceTokenPlaying(sequenceRow, event.symbol, false);
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
            primedTextEl.textContent =
                `Exercise ${currentExerciseIndex} of ${currentExercises.length}`;
        }
        li.textContent  = formatSymbolReview(event);
        li.dataset.kind = "symbol";
        li.dataset.exerciseIndex = String(event.exercise_index);
        li.dataset.wordIndex = String(event.word_index);

    } else if (event.type === "session-start") {
        currentExercises = Array.isArray(event.exercises) ? event.exercises : [];
        currentExerciseIndex = 0;
        currentSetSession = event.koch_set_session || event.set_session || 0;
        currentKochGears = Array.isArray(event.koch_gears) ? event.koch_gears : currentKochGears;
        currentKochWarmUp = event.koch_warm_up === true || event.warm_up === true;
        sessionActive   = true;
        sessionStartedAtMs = Date.now();
        claimedState.set_is_fresh = false;
        setStartButtonMode("active");

        const meta = toggleBtn.querySelector(".timeline-meta");
        const warmUpLabel = event.warm_up ? " · warm-up" : "";
        meta.textContent =
            `seed ${event.seed} · ${currentExercises.length} exercises${warmUpLabel}`;

        setTimelineLocked(true);
        setTimelineOpen(false);
        setActiveTab("answers");
        eventsEl.replaceChildren();
        buildAnswerInputs(currentExercises);
        setSaveState("locked");
        primedTextEl.textContent = `Exercise — of ${currentExercises.length}`;
        primedSetEl.textContent = kochSetNotice();
        return;

    } else if (event.type === "session-end") {
        sessionActive     = false;
        li.textContent    = "■ end";
        li.dataset.kind   = "end";
        setStartButtonMode(currentSetSession >= SET_SIZE ? "end" : "idle");
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
        revealSentColumn();
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
        if (claimedState.set_is_fresh) {
            startBtn.innerHTML = "<u>S</u>tart";
        } else {
            startBtn.innerHTML = "Continue (<u>S</u>)";
        }
    } else if (mode === "counting") {
        startBtn.disabled    = false;
        startBtn.textContent = "Cancel";
    } else if (mode === "active") {
        clearCountdown();
        startBtn.disabled    = false;
        startBtn.textContent = "Abort";
    } else if (mode === "end") {
        clearCountdown();
        startBtn.disabled    = false;
        startBtn.textContent = "End";
    }
}

function clearCountdown() {
    clearCountdownCore(countdownEl, countdownTimer);
    countdownTimer = null;
}

function beginCountdownThenStart() {
    resetReviewSection();
    countdownTimer = startCountdown(countdownEl, startBtn, COUNTDOWN_SECONDS, () => {
        countdownTimer = null;
        if (!socket || socket.readyState !== WebSocket.OPEN) {
            setStartButtonMode("idle");
            return;
        }
        socket.send(JSON.stringify({ action: "start" }));
        startBtn.disabled = true;
    });
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
    if (mode === "end") {
        // Set complete — reset to a clean Start position. No engine
        // action; the engine already wrapped its state after session 8.
        currentSetSession = 0;
        claimedState.set_is_fresh = true;
        resetReviewSection();
        setStartButtonMode("idle");
        renderPrimed();
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

installClaimHandlers(sequenceRow, () => socket, () => sessionActive);
socket = connectKoch({
    onOpen() { setStartButtonMode("idle"); },
    onMessage: appendEvent,
    onClose() {
        clearCountdown();
        startBtn.disabled  = true;
        sessionActive      = false;
        sessionStartedAtMs = null;
        setSaveState("locked");
        setTimelineLocked(false);
    },
});
