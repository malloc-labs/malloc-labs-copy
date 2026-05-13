// Copy — Key timing page.
//
// Read-only sequence display for known symbols. The engine pushes the same
// claimed-symbols event used by Koch Exercises; this page only renders it.

const wsUrl = `ws://${location.host}/ws`;

const statusEl = document.querySelector(".status");
const sequenceRow = document.getElementById("sequence-row");
const sentSymbolEl = document.getElementById("sent-symbol");
const sentPatternEl = document.getElementById("sent-pattern");
const sentHistoryEl = document.getElementById("sent-history");

const MAX_SENT_HISTORY = 8;

// Canonical Koch order — mirrors KOCH_ORDER in patterns.py.
const KOCH_ORDER = [
    "K", "M", "U", "R", "E", "S", "N", "A", "P", "T",
    "L", "W", "I", ".", "J", "Z", "=", "F", "O", "Y",
    ",", "V", "G", "5", "/", "Q", "9", "2", "H", "3",
    "8", "B", "?", "4", "7", "C", "1", "D", "6", "0", "X",
];

function setStatus(state, text) {
    statusEl.dataset.status = state;
    statusEl.textContent = text;
}

function buildSequenceRow() {
    sequenceRow.replaceChildren();
    KOCH_ORDER.forEach((sym) => {
        const token = document.createElement("span");
        token.textContent = sym;
        token.dataset.symbol = sym;
        token.dataset.state = "available";
        token.setAttribute("role", "listitem");
        token.classList.add("seq-token");
        sequenceRow.appendChild(token);
    });
}

function renderSequence(state) {
    const claimedSet = new Set(state.symbols);
    const next = state.suggested_next;

    KOCH_ORDER.forEach((sym) => {
        const token = sequenceRow.querySelector(`[data-symbol="${CSS.escape(sym)}"]`);
        if (!token) return;

        if (claimedSet.has(sym)) {
            token.dataset.state = "claimed";
            token.title = `${sym} — known`;
        } else if (sym === next) {
            token.dataset.state = "next";
            token.title = `${sym} — next in sequence`;
        } else {
            token.dataset.state = "available";
            token.title = `${sym} — not yet known`;
        }
    });
}

function renderSentSymbol(event) {
    const symbol = event.symbol || "?";
    sentSymbolEl.textContent = symbol;
    sentPatternEl.textContent = event.pattern;

    const item = document.createElement("li");
    const symbolEl = document.createElement("span");
    const patternEl = document.createElement("span");
    symbolEl.className = "key-sent-history__symbol";
    patternEl.className = "key-sent-history__pattern";
    symbolEl.textContent = symbol;
    patternEl.textContent = event.pattern;
    item.replaceChildren(symbolEl, patternEl);
    sentHistoryEl.prepend(item);

    while (sentHistoryEl.children.length > MAX_SENT_HISTORY) {
        sentHistoryEl.lastElementChild.remove();
    }
}

function connect() {
    setStatus("connecting", "connecting...");
    const socket = new WebSocket(wsUrl);

    socket.addEventListener("open", () => {
        setStatus("connected", "connected");
        socket.send(JSON.stringify({ action: "start-key-input" }));
    });

    socket.addEventListener("message", (message) => {
        const event = JSON.parse(message.data);
        if (event.type === "claimed-symbols") {
            renderSequence(event);
        } else if (event.type === "sent-symbol") {
            renderSentSymbol(event);
        } else if (event.type === "key-input-start") {
            setStatus("connected", "key ready");
        } else if (event.type === "error") {
            const midiError = event.reason === "key-input-unavailable" ||
                event.reason === "key-input-failed";
            setStatus("connecting", midiError ? "midi unavailable" : "error");
        }
    });

    socket.addEventListener("close", () => {
        setStatus("connecting", "disconnected");
    });
}

buildSequenceRow();
connect();
