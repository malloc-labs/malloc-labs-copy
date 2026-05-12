// Copy — Letters page (Koch hub).
//
// One WebSocket to the engine. Click a cell to send {action: "play-letter",
// symbol}; the engine plays the wav + morse listening sequence on its
// audio output. While a sequence runs, the corresponding cell shows a
// quiet active state. A second click on a different letter supersedes
// the first — the server cancels the in-flight sequence and starts the
// new one (spec §1.4 / §2.6).
//
// Cells are disabled until the WebSocket opens so a click before the
// engine is reachable does nothing surprising. No retries on close —
// the page is not the right surface for an offline reconnect loop.

import { PATTERNS, displayMorsePattern, spokenMorsePattern } from "./morse-display.js";

const wsUrl = `ws://${location.host}/ws`;
const cells = document.querySelectorAll(".letter-cell");
const toggleBtn = document.querySelector(".timeline-toggle");
const truthBody = document.querySelector(".timeline-body");
const truthEvents = document.getElementById("symbol-truth-events");
const truthMeta = toggleBtn.querySelector(".timeline-meta");
let socket = null;
let lastCompletedSymbol = null;

function setActiveCell(letter) {
    cells.forEach((c) => {
        c.dataset.active = c.dataset.letter === letter ? "true" : "false";
    });
}

function clearActiveCells() {
    cells.forEach((c) => {
        c.dataset.active = "false";
    });
}

function setCellsEnabled(enabled) {
    cells.forEach((c) => {
        c.disabled = !enabled;
    });
}

function setTruthOpen(open) {
    const arrow = toggleBtn.querySelector(".timeline-arrow");
    if (open) {
        truthBody.hidden = false;
        arrow.textContent = "▼";
        toggleBtn.setAttribute("aria-expanded", "true");
    } else {
        truthBody.hidden = true;
        arrow.textContent = "▶";
        toggleBtn.setAttribute("aria-expanded", "false");
    }
}

function setTruthLocked(locked) {
    if (locked) {
        toggleBtn.setAttribute("aria-disabled", "true");
        toggleBtn.classList.add("timeline-toggle--locked");
    } else {
        toggleBtn.removeAttribute("aria-disabled");
        toggleBtn.classList.remove("timeline-toggle--locked");
    }
}

function renderTruth(symbol) {
    const pattern = PATTERNS[symbol];
    if (!pattern) {
        truthMeta.textContent = `${symbol} · no pattern`;
        truthEvents.replaceChildren();
        return;
    }

    truthMeta.textContent = `${symbol} · pattern`;
    const li = document.createElement("li");
    li.dataset.kind = "symbol";

    const symbolLine = document.createElement("span");
    symbolLine.className = "symbol-truth-line symbol-truth-symbol";
    symbolLine.textContent = symbol;

    const spokenLine = document.createElement("span");
    spokenLine.className = "symbol-truth-line symbol-truth-spoken";
    spokenLine.textContent = spokenMorsePattern(pattern);

    const morseLine = document.createElement("span");
    morseLine.className = "symbol-truth-line symbol-truth-morse";
    morseLine.textContent = displayMorsePattern(pattern);

    li.replaceChildren(symbolLine, spokenLine, morseLine);
    truthEvents.replaceChildren(li);
}

toggleBtn.addEventListener("click", () => {
    if (toggleBtn.getAttribute("aria-disabled") === "true") return;
    const isOpen = toggleBtn.getAttribute("aria-expanded") === "true";
    setTruthOpen(!isOpen);
});

function connect() {
    socket = new WebSocket(wsUrl);

    socket.addEventListener("open", () => {
        setCellsEnabled(true);
    });

    socket.addEventListener("message", (msg) => {
        let event;
        try {
            event = JSON.parse(msg.data);
        } catch {
            return;
        }
        // The server pushes claimed-symbols on connect on the same WS
        // that drives the Exercises page; ignore here.
        if (event.type === "letter-start") {
            lastCompletedSymbol = null;
            setActiveCell(event.symbol);
            truthMeta.textContent = "listening…";
            truthEvents.replaceChildren();
            setTruthOpen(false);
            setTruthLocked(true);
        } else if (event.type === "letter-end") {
            lastCompletedSymbol = event.symbol;
            clearActiveCells();
            renderTruth(event.symbol);
            setTruthLocked(false);
        } else if (event.type === "error") {
            lastCompletedSymbol = null;
            clearActiveCells();
            truthMeta.textContent = "—";
            truthEvents.replaceChildren();
            setTruthOpen(false);
            setTruthLocked(true);
        }
    });

    socket.addEventListener("close", () => {
        setCellsEnabled(false);
        clearActiveCells();
        if (!lastCompletedSymbol) {
            truthMeta.textContent = "—";
            truthEvents.replaceChildren();
            setTruthOpen(false);
            setTruthLocked(true);
        }
    });

    socket.addEventListener("error", () => {
        // The close handler will fire next and disable cells. Nothing
        // useful to do here — the WS API does not give us a reason.
    });
}

cells.forEach((cell) => {
    cell.addEventListener("click", () => {
        if (!socket || socket.readyState !== WebSocket.OPEN) return;
        const letter = cell.dataset.letter;
        // Optimistic local active state — the server's letter-start
        // frame will confirm or correct this within a frame or two.
        setActiveCell(letter);
        socket.send(JSON.stringify({ action: "play-letter", symbol: letter }));
    });
});

setCellsEnabled(false);
setTruthOpen(false);
setTruthLocked(true);
connect();
