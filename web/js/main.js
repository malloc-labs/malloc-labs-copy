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
const playBtn = document.getElementById("play-kmk");
const stopBtn = document.getElementById("stop");

let socket = null;

function setStatus(state, text) {
    statusEl.dataset.status = state;
    statusEl.textContent = text;
}

function appendEvent(event) {
    const li = document.createElement("li");
    if (event.type === "symbol") {
        const t = event.t_on.toFixed(2);
        li.textContent = `${t}s  ${event.symbol}`;
        li.dataset.kind = "symbol";
    } else if (event.type === "session-start") {
        li.textContent = `▶ ${event.symbols}`;
        li.dataset.kind = "start";
    } else if (event.type === "session-end") {
        li.textContent = "■ end";
        li.dataset.kind = "end";
        playBtn.disabled = false;
        stopBtn.disabled = true;
    } else if (event.type === "error") {
        li.textContent = `! ${event.reason}${event.symbol ? `: ${event.symbol}` : ""}`;
        li.dataset.kind = "error";
        playBtn.disabled = false;
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
        playBtn.disabled = false;
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
        playBtn.disabled = true;
        stopBtn.disabled = true;
    });

    socket.addEventListener("error", () => {
        setStatus("error", "connection error");
    });
}

playBtn.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    eventsEl.replaceChildren();
    socket.send(JSON.stringify({ action: "play", symbols: "KMK" }));
    playBtn.disabled = true;
    stopBtn.disabled = false;
});

stopBtn.addEventListener("click", () => {
    // Stop is the only listening-screen affordance per spec §4.1/4.2;
    // wired to no-op until session/ implements cancellation.
    stopBtn.disabled = true;
});

connect();
