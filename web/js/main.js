// Copy — minimal v0 UI shell.
//
// One WebSocket to the engine. Send JSON commands; render the events
// the engine pushes back as a plain timeline. No state machine, no
// framework, no buildstep (spec §12).
//
// This file is a development scaffold for the engine ↔ UI seam. It
// will be reshaped once Detection and Full Copy modes land; the
// listening screen affordance budget is five (spec §8.3).

const wsUrl = `ws://${location.host}/ws`;

const statusEl     = document.querySelector(".status");
const eventsEl     = document.getElementById("events");
const startBtn     = document.getElementById("start");
const stopBtn      = document.getElementById("stop");
const clearBtn     = document.getElementById("clear");
const sequenceRow  = document.getElementById("sequence-row");
const primedEl     = document.getElementById("primed");

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
let claimedState    = { symbols: [], suggested_next: null };
let sessionDuration = 30; // updated from session-start
let sessionActive   = false;

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
    const next = state.suggested_next;

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
        `Primed: ${sessionDuration}s of ${claimedState.symbols.join(", ")} (uniform random)`;
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

// ─── Status ───────────────────────────────────────────────────────────────────

function setStatus(state, text) {
    statusEl.dataset.status = state;
    statusEl.textContent    = text;
}

// ─── Event rendering ──────────────────────────────────────────────────────────

function appendEvent(event) {
    if (event.type === "claimed-symbols") {
        renderSequence(event);
        return;
    }

    const li = document.createElement("li");

    if (event.type === "symbol") {
        li.textContent  = `${event.t_on.toFixed(2)}s  ${event.symbol}`;
        li.dataset.kind = "symbol";

    } else if (event.type === "session-start") {
        sessionDuration = event.duration_seconds;
        sessionActive   = true;

        const meta = toggleBtn.querySelector(".timeline-meta");
        meta.textContent =
            `seed ${event.seed} · ${event.symbols.length} symbols · ${event.duration_seconds}s`;

        setTimelineLocked(true);
        setTimelineOpen(false);
        eventsEl.replaceChildren();
        renderPrimed();
        return;

    } else if (event.type === "session-end") {
        sessionActive     = false;
        li.textContent    = "■ end";
        li.dataset.kind   = "end";
        startBtn.disabled = false;
        stopBtn.disabled  = true;
        clearBtn.disabled = false;
        setTimelineLocked(false);

    } else if (event.type === "error") {
        const detail = event.detail ? `: ${event.detail}`
                     : event.symbol ? `: ${event.symbol}`
                     : "";
        li.textContent    = `! ${event.reason}${detail}`;
        li.dataset.kind   = "error";
        startBtn.disabled = false;
        stopBtn.disabled  = true;
        clearBtn.disabled = false;
        sessionActive     = false;
        setTimelineLocked(false);

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
        stopBtn.disabled  = true;
        clearBtn.disabled = true;
        sessionActive     = false;
        setTimelineLocked(false);
    });

    socket.addEventListener("error", () => {
        setStatus("error", "connection error");
    });
}

// ─── Controls ─────────────────────────────────────────────────────────────────

startBtn.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ action: "start" }));
    startBtn.disabled = true;
    stopBtn.disabled  = false;
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
    setTimelineOpen(false);
    setTimelineLocked(true);
    clearBtn.disabled = true;
});

// ─── Init ─────────────────────────────────────────────────────────────────────

buildSequenceRow();
connect();
