// Copy — shared Koch page infrastructure.
//
// Sequence rendering, claim/unclaim handlers, status, and WS
// connection lifecycle used by both the Koch Exercise and Symbol
// Recognition pages. Each page imports what it needs and layers
// its own concerns on top.

import { KOCH_ORDER } from "./partials/koch-sequence.js";

export { KOCH_ORDER };

export const PERMANENT = new Set(["K", "M"]);

// ─── Status ──────────────────────────────────────────────────────────────────

export function setStatus(state, text) {
    const el = document.querySelector(".status");
    el.dataset.status = state;
    el.textContent    = text;
}

// ─── Sequence rendering ──────────────────────────────────────────────────────

export function renderSequence(sequenceRow, state) {
    const claimedSet = new Set(state.symbols);
    sequenceRow.dataset.evidence = state.evidence_ready_for_next ? "true" : "false";
    sequenceRow.dataset.ready = state.ready_for_next ? "true" : "false";
    const next = state.suggested_next;

    KOCH_ORDER.forEach((sym) => {
        const btn = sequenceRow.querySelector(`[data-symbol="${CSS.escape(sym)}"]`);
        if (!btn) return;

        if (claimedSet.has(sym)) {
            btn.dataset.state = "claimed";
            btn.disabled = PERMANENT.has(sym);
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

    return claimedSet;
}

export function setSequenceTokenPlaying(sequenceRow, symbol, playing) {
    sequenceRow.querySelectorAll("[data-playing]").forEach((el) => {
        delete el.dataset.playing;
    });
    if (!playing || !symbol) return;
    const token = sequenceRow.querySelector(`[data-symbol="${CSS.escape(symbol)}"]`);
    if (token) token.dataset.playing = "true";
}

// ─── Claim handlers ──────────────────────────────────────────────────────────

export function installClaimHandlers(sequenceRow, getSocket, isBlocked) {
    KOCH_ORDER.forEach((sym) => {
        const btn = sequenceRow.querySelector(`[data-symbol="${CSS.escape(sym)}"]`);
        if (!btn) return;
        btn.addEventListener("click", () => {
            const socket = getSocket();
            if (!socket || socket.readyState !== WebSocket.OPEN) return;
            if (isBlocked && isBlocked()) return;
            if (btn.dataset.state === "claimed") {
                if (PERMANENT.has(sym)) return;
                socket.send(JSON.stringify({ action: "unclaim-symbol", symbol: sym }));
            } else {
                socket.send(JSON.stringify({ action: "claim-symbol", symbol: sym }));
            }
        });
    });
}

// ─── WebSocket connection ────────────────────────────────────────────────────

export function connectKoch({ onOpen, onMessage, onClose }) {
    const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProtocol}//${location.host}/ws`;
    const socket = new WebSocket(wsUrl);

    socket.addEventListener("open", () => {
        setStatus("connected", "connected");
        if (onOpen) onOpen();
    });

    socket.addEventListener("message", (msg) => {
        let event;
        try {
            event = JSON.parse(msg.data);
        } catch {
            event = { type: "error", reason: "invalid-json-from-engine" };
        }
        onMessage(event);
    });

    socket.addEventListener("close", () => {
        setStatus("disconnected", "disconnected");
        if (onClose) onClose();
    });

    socket.addEventListener("error", () => {
        setStatus("error", "connection error");
    });

    return socket;
}
