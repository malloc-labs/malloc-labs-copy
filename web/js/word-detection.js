// Copy — Word Detection exercise UI.
//
// This page deliberately mirrors the Koch exercise truth disclosure: the
// engine sends the full truth during playback, but the disclosure remains
// locked until session-end so answers are not available while listening.

import { PATTERNS, spokenMorsePattern } from "./morse-display.js";

const wsUrl = `ws://${location.host}/ws`;

const statusEl    = document.querySelector(".status");
const eventsEl    = document.getElementById("events");
const startBtn    = document.getElementById("start");
const stopBtn     = document.getElementById("stop");
const clearBtn    = document.getElementById("clear");
const focusRow    = document.getElementById("focus-row");
const primedEl    = document.getElementById("primed");
const toggleBtn   = document.querySelector(".timeline-toggle");
const timelineBody = document.querySelector(".timeline-body");

let socket = null;
let claimedState = { symbols: [], suggested_next: null };
let sessionDuration = 30;
let sessionActive = false;
let lastWordIndex = null;
let sessionStartedAtMs = null;

function setStatus(state, text) {
    statusEl.dataset.status = state;
    statusEl.textContent = text;
}

function setTimelineOpen(open) {
    const arrow = toggleBtn.querySelector(".timeline-arrow");
    if (open) {
        timelineBody.hidden = false;
        arrow.textContent = "▼";
        toggleBtn.setAttribute("aria-expanded", "true");
    } else {
        timelineBody.hidden = true;
        arrow.textContent = "▶";
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

function renderFocus(state) {
    claimedState = state;
    focusRow.replaceChildren();

    state.symbols.forEach((sym) => {
        const token = document.createElement("span");
        token.textContent = sym;
        token.dataset.symbol = sym;
        token.dataset.state = "claimed";
        token.setAttribute("role", "listitem");
        token.classList.add("seq-token");
        focusRow.appendChild(token);
    });

    renderPrimed();
}

function renderPrimed() {
    if (!claimedState.symbols.length) {
        primedEl.textContent = "Primed: nothing — claim symbols on the Koch Exercise page first";
        return;
    }
    primedEl.textContent =
        `Primed: ${sessionDuration}s of focus-word detection for ${claimedState.symbols.join(", ")}`;
}

function appendWordHeader(wordIndex, word) {
    const li = document.createElement("li");
    li.textContent = `Word ${wordIndex}: ${word}`;
    li.dataset.kind = "word";
    eventsEl.appendChild(li);
}

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
        renderFocus(event);
        return;
    }

    const li = document.createElement("li");

    if (event.type === "session-start") {
        sessionDuration = event.duration_seconds;
        sessionActive = true;
        lastWordIndex = null;
        sessionStartedAtMs = Date.now();

        const meta = toggleBtn.querySelector(".timeline-meta");
        meta.textContent = `seed ${event.seed} · ${event.word_count ?? event.words.length} words`;

        setTimelineLocked(true);
        setTimelineOpen(false);
        eventsEl.replaceChildren();
        renderPrimed();
        return;

    } else if (event.type === "symbol") {
        if (event.word_index !== lastWordIndex) {
            appendWordHeader(event.word_index, event.word);
            lastWordIndex = event.word_index;
        }
        li.textContent = formatSymbolReview(event);
        li.dataset.kind = "symbol";

    } else if (event.type === "session-end") {
        sessionActive = false;
        li.textContent = "■ end";
        li.dataset.kind = "end";
        startBtn.disabled = false;
        stopBtn.disabled = true;
        clearBtn.disabled = false;
        sessionStartedAtMs = null;
        setTimelineLocked(false);

    } else if (event.type === "error") {
        const detail = event.detail ? `: ${event.detail}`
                     : event.symbol ? `: ${event.symbol}`
                     : "";
        li.textContent = `! ${event.reason}${detail}`;
        li.dataset.kind = "error";
        startBtn.disabled = false;
        stopBtn.disabled = true;
        clearBtn.disabled = false;
        sessionActive = false;
        sessionStartedAtMs = null;
        setTimelineLocked(false);

    } else {
        li.textContent = JSON.stringify(event);
    }

    eventsEl.appendChild(li);
}

function connect() {
    socket = new WebSocket(wsUrl);

    socket.addEventListener("open", () => {
        setStatus("connected", "connected");
        startBtn.disabled = false;
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
        startBtn.disabled = true;
        stopBtn.disabled = true;
        clearBtn.disabled = true;
        sessionActive = false;
        sessionStartedAtMs = null;
        setTimelineLocked(false);
    });

    socket.addEventListener("error", () => {
        setStatus("error", "connection error");
    });
}

startBtn.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ action: "start-word-detection" }));
    startBtn.disabled = true;
    stopBtn.disabled = false;
});

stopBtn.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ action: "stop" }));
    stopBtn.disabled = true;
});

clearBtn.addEventListener("click", () => {
    eventsEl.replaceChildren();
    const meta = toggleBtn.querySelector(".timeline-meta");
    meta.textContent = "—";
    lastWordIndex = null;
    sessionStartedAtMs = null;
    setTimelineOpen(false);
    setTimelineLocked(true);
    clearBtn.disabled = true;
});

setTimelineOpen(false);
setTimelineLocked(true);
connect();
