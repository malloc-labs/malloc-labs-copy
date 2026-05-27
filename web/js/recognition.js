// Copy — Symbol Recognition UI.
//
// Connects to the engine, renders the claimed symbol set, and drives
// recognition training sessions. The training flow is entirely
// audio — the learner does not interact with the screen once a
// session starts. Truth is disclosed after session-end.

import {
    clearCountdown as clearCountdownCore,
    connectKoch,
    installClaimHandlers,
    renderSequence,
    setSequenceTokenPlaying,
    startCountdown,
} from "./koch-core.js";

const sequenceRow  = document.getElementById("sequence-row");
const startBtn     = document.getElementById("start");
const countdownEl  = document.getElementById("countdown");
const primedTextEl = document.getElementById("primed-text");
const primedSetEl  = document.getElementById("primed-set");
const eventsEl     = document.getElementById("events");
const toggleBtn    = document.querySelector(".timeline-toggle");
const timelineBody = document.querySelector(".timeline-body");

const COUNTDOWN_SECONDS = 5;
const SET_SIZE = 8;

let socket = null;
let countdownTimer = null;
let claimedState = { symbols: [], suggested_next: null, set_is_fresh: true };
let sessionActive = false;
let currentExercises = [];
let currentExerciseIndex = 0;
let currentSetSession = 0;

// ─── Primed ──────────────────────────────────────────────────────────────────

function renderPrimed() {
    if (!claimedState.symbols.length) {
        primedTextEl.textContent = "Primed: nothing — claim a symbol first";
        primedSetEl.textContent = "";
        return;
    }
    primedTextEl.textContent =
        `Recognition: ${claimedState.symbols.join(", ")}`;
    primedSetEl.textContent = currentSetSession > 0
        ? `Set ${currentSetSession} of ${SET_SIZE}`
        : "";
}

// ─── Timeline disclosure ─────────────────────────────────────────────────────

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

// ─── Controls ────────────────────────────────────────────────────────────────

function clearCountdown() {
    clearCountdownCore(countdownEl, countdownTimer);
    countdownTimer = null;
}

function setStartButtonMode(mode) {
    startBtn.dataset.mode = mode;
    if (mode === "idle") {
        clearCountdown();
        startBtn.disabled = !socket || socket.readyState !== WebSocket.OPEN;
        startBtn.innerHTML = "<u>S</u>tart";
    } else if (mode === "counting") {
        startBtn.disabled = false;
        startBtn.textContent = "Cancel";
    } else if (mode === "active") {
        clearCountdown();
        startBtn.disabled = false;
        startBtn.textContent = "Abort";
    } else if (mode === "end") {
        clearCountdown();
        startBtn.disabled = false;
        startBtn.textContent = "End";
    }
}

function beginCountdownThenStart() {
    eventsEl.replaceChildren();
    const meta = toggleBtn.querySelector(".timeline-meta");
    meta.textContent = "—";
    setTimelineOpen(false);
    setTimelineLocked(true);

    countdownTimer = startCountdown(countdownEl, startBtn, COUNTDOWN_SECONDS, () => {
        countdownTimer = null;
        if (!socket || socket.readyState !== WebSocket.OPEN) {
            setStartButtonMode("idle");
            return;
        }
        socket.send(JSON.stringify({ action: "start-recognition" }));
        startBtn.disabled = true;
    });
}

startBtn.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const mode = startBtn.dataset.mode;
    if (mode === "active") {
        socket.send(JSON.stringify({ action: "stop" }));
        startBtn.disabled = true;
        return;
    }
    if (mode === "counting") {
        setStartButtonMode("idle");
        return;
    }
    if (mode === "end") {
        currentSetSession = 0;
        eventsEl.replaceChildren();
        setStartButtonMode("idle");
        renderPrimed();
        return;
    }
    beginCountdownThenStart();
});

// ─── Start keybind (S) ──────────────────────────────────────────────────────

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

// ─── Event handling ──────────────────────────────────────────────────────────

function appendEvent(event) {
    if (event.type === "claimed-symbols") {
        claimedState = event;
        renderSequence(sequenceRow, event);
        renderPrimed();
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

    if (event.type === "session-start") {
        currentExercises = Array.isArray(event.exercises) ? event.exercises : [];
        currentExerciseIndex = 0;
        currentSetSession = event.set_session || 0;
        sessionActive = true;
        setStartButtonMode("active");
        const meta = toggleBtn.querySelector(".timeline-meta");
        meta.textContent = `seed ${event.seed} · ${currentExercises.length} exercises`;
        setTimelineLocked(true);
        setTimelineOpen(false);
        eventsEl.replaceChildren();
        primedTextEl.textContent = `Exercise — of ${currentExercises.length}`;
        primedSetEl.textContent = currentSetSession > 0
            ? `Set ${currentSetSession} of ${SET_SIZE}`
            : "";
        return;
    }

    if (event.type === "symbol") {
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
        const li = document.createElement("li");
        li.textContent = `${event.symbol}`;
        li.dataset.kind = "symbol";
        li.dataset.exerciseIndex = String(event.exercise_index);
        eventsEl.appendChild(li);
        return;
    }

    if (event.type === "session-end") {
        sessionActive = false;
        const li = document.createElement("li");
        li.textContent = "■ end";
        li.dataset.kind = "end";
        eventsEl.appendChild(li);
        setStartButtonMode(currentSetSession >= SET_SIZE ? "end" : "idle");
        setTimelineLocked(false);
        renderPrimed();
        return;
    }

    if (event.type === "error") {
        const detail = event.detail ? `: ${event.detail}` : "";
        const li = document.createElement("li");
        li.textContent = `! ${event.reason}${detail}`;
        li.dataset.kind = "error";
        eventsEl.appendChild(li);
        setStartButtonMode("idle");
        sessionActive = false;
        setTimelineLocked(false);
        return;
    }
}

// ─── Init ────────────────────────────────────────────────────────────────────

installClaimHandlers(sequenceRow, () => socket, () => sessionActive);
socket = connectKoch({
    onOpen() { setStartButtonMode("idle"); },
    onMessage: appendEvent,
    onClose() {
        clearCountdown();
        startBtn.disabled = true;
        sessionActive = false;
        setTimelineLocked(false);
    },
});
