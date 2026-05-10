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

const statusEl         = document.querySelector(".status");
const eventsEl         = document.getElementById("events");
const startBtn         = document.getElementById("start");
const stopBtn          = document.getElementById("stop");
const clearBtn         = document.getElementById("clear");
const claimedEl        = document.getElementById("claimed-symbols");
const claimSuggestedEl = document.getElementById("claim-suggested");
const suggestedNextEl  = document.getElementById("suggested-next");
const claimBtn         = document.getElementById("claim-button");
const primedEl         = document.getElementById("primed");

// Latest claimed-symbols payload from the engine. Held so the primed
// line can describe what Start will do without re-asking the engine.
let claimedState    = { symbols: [], suggested_next: null };
let sessionDuration = 30; // updated from session-start; default for the primed line
let sessionActive   = false; // true while a session is in flight

let socket = null;

// ─── Timeline disclosure ──────────────────────────────────────────────────────
// The timeline section contains a <button class="timeline-toggle"> header row
// and a <div class="timeline-body"> that holds the <ol id="events">.
// The toggle is disabled (aria-disabled) while a session is active.
// On session-end the toggle becomes interactive and the body stays collapsed
// until the learner explicitly opens it — listening first, review later.

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
    // aria-disabled keeps the element in the tab order and visible but
    // communicates it is not yet interactive (session still running).
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

// Initialise: collapsed and locked (no session yet)
setTimelineOpen(false);
setTimelineLocked(true);

// ─── Status ───────────────────────────────────────────────────────────────────

function setStatus(state, text) {
    statusEl.dataset.status = state;
    statusEl.textContent    = text;
}

// ─── Claimed / primed ─────────────────────────────────────────────────────────

function renderClaimed(state) {
    claimedState = state;
    claimedEl.textContent = state.symbols.length ? state.symbols.join(" ") : "—";

    if (state.suggested_next) {
        suggestedNextEl.textContent = state.suggested_next;
        claimSuggestedEl.hidden     = false;
        claimBtn.textContent        = `Claim ${state.suggested_next}`;
        claimBtn.hidden             = false;
        claimBtn.disabled           = false;
    } else {
        claimSuggestedEl.hidden = true;
        claimBtn.hidden         = true;
    }
    renderPrimed();
}

function renderPrimed() {
    if (!claimedState.symbols.length) {
        primedEl.textContent = "Primed: nothing — claim a symbol first";
        return;
    }
    primedEl.textContent =
        `Primed: ${sessionDuration}s of ${claimedState.symbols.join(", ")} (uniform random)`;
}

// ─── Event rendering ──────────────────────────────────────────────────────────

function appendEvent(event) {
    if (event.type === "claimed-symbols") {
        renderClaimed(event);
        return;
    }

    const li = document.createElement("li");

    if (event.type === "symbol") {
        li.textContent  = `${event.t_on.toFixed(2)}s  ${event.symbol}`;
        li.dataset.kind = "symbol";

    } else if (event.type === "session-start") {
        sessionDuration = event.duration_seconds;
        sessionActive   = true;

        // Update the toggle header with seed / count / duration
        const meta = toggleBtn.querySelector(".timeline-meta");
        meta.textContent =
            `seed ${event.seed} · ${event.symbols.length} symbols · ${event.duration_seconds}s`;

        // Lock the toggle and keep it collapsed during the session
        setTimelineLocked(true);
        setTimelineOpen(false);

        // Clear any previous run's events
        eventsEl.replaceChildren();

        renderPrimed();
        return; // no <li> for session-start — toggle header carries the info

    } else if (event.type === "session-end") {
        sessionActive     = false;
        li.textContent    = "■ end";
        li.dataset.kind   = "end";
        startBtn.disabled = false;
        stopBtn.disabled  = true;
        clearBtn.disabled = false;

        // Unlock the toggle — learner can now review if they choose
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
        claimBtn.disabled = true;
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

claimBtn.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    if (!claimedState.suggested_next) return;
    socket.send(
        JSON.stringify({ action: "claim-symbol", symbol: claimedState.suggested_next }),
    );
});

clearBtn.addEventListener("click", () => {
    // Reset the timeline display and toggle back to initial state.
    // Does not affect the engine or claimed symbols.
    eventsEl.replaceChildren();
    const meta = toggleBtn.querySelector(".timeline-meta");
    meta.textContent = "—";
    setTimelineOpen(false);
    setTimelineLocked(true);
    clearBtn.disabled = true;
});

connect();
