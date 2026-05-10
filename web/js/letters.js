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

const wsUrl = `ws://${location.host}/ws`;
const cells = document.querySelectorAll(".letter-cell");
let socket = null;

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
            setActiveCell(event.symbol);
        } else if (event.type === "letter-end") {
            clearActiveCells();
        }
    });

    socket.addEventListener("close", () => {
        setCellsEnabled(false);
        clearActiveCells();
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
connect();
