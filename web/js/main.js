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
const statusEl = document.querySelector(".status");
const eventsEl = document.getElementById("events");
const startBtn = document.getElementById("start");
const stopBtn = document.getElementById("stop");
const claimedEl = document.getElementById("claimed-symbols");
const claimSuggestedEl = document.getElementById("claim-suggested");
const suggestedNextEl = document.getElementById("suggested-next");
const claimBtn = document.getElementById("claim-button");
const primedEl = document.getElementById("primed");

// Latest claimed-symbols payload from the engine. Held so the primed
// line can describe what Start will do without re-asking the engine.
let claimedState = { symbols: [], suggested_next: null };
let sessionDuration = 30; // updated from session-start; default for the primed line
let socket = null;

function setStatus(state, text) {
    statusEl.dataset.status = state;
    statusEl.textContent = text;
}

function renderClaimed(state) {
    claimedState = state;
    claimedEl.textContent = state.symbols.length ? state.symbols.join(" ") : "—";

    if (state.suggested_next) {
        suggestedNextEl.textContent = state.suggested_next;
        claimSuggestedEl.hidden = false;
        claimBtn.textContent = `Claim ${state.suggested_next}`;
        claimBtn.hidden = false;
        claimBtn.disabled = false;
    } else {
        claimSuggestedEl.hidden = true;
        claimBtn.hidden = true;
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

function appendEvent(event) {
    if (event.type === "claimed-symbols") {
        renderClaimed(event);
        return;
    }

    const li = document.createElement("li");
    if (event.type === "symbol") {
        li.textContent = `${event.t_on.toFixed(2)}s  ${event.symbol}`;
        li.dataset.kind = "symbol";
    } else if (event.type === "session-start") {
        sessionDuration = event.duration_seconds;
        li.textContent = `▶ seed ${event.seed} · ${event.symbols.length} symbols · ${event.duration_seconds}s`;
        li.dataset.kind = "start";
        renderPrimed();
    } else if (event.type === "session-end") {
        li.textContent = "■ end";
        li.dataset.kind = "end";
        startBtn.disabled = false;
        stopBtn.disabled = true;
    } else if (event.type === "error") {
        const detail = event.detail ? `: ${event.detail}` : event.symbol ? `: ${event.symbol}` : "";
        li.textContent = `! ${event.reason}${detail}`;
        li.dataset.kind = "error";
        startBtn.disabled = false;
        stopBtn.disabled = true;
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
        claimBtn.disabled = true;
    });

    socket.addEventListener("error", () => {
        setStatus("error", "connection error");
    });
}

startBtn.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    eventsEl.replaceChildren();
    socket.send(JSON.stringify({ action: "start" }));
    startBtn.disabled = true;
    stopBtn.disabled = false;
});

stopBtn.addEventListener("click", () => {
    // Stop is the only listening-screen affordance per spec §4.1/4.2;
    // wired to no-op until session/ implements cancellation.
    stopBtn.disabled = true;
});

claimBtn.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    if (!claimedState.suggested_next) return;
    socket.send(
        JSON.stringify({ action: "claim-symbol", symbol: claimedState.suggested_next }),
    );
});

connect();
