// Copy — Key Training page entry.
//
// First slice: expose the same interactive Koch sequence used by
// Symbol Recognition so claimed symbols can be managed from Key
// Training. The actual training-session lifecycle is intentionally
// deferred until the keyer-mode progression model is settled.

import {
    connectKoch,
    installClaimHandlers,
    renderSequence,
    setSequenceTokenPlaying,
} from "./koch-core.js";
import { hideSymbolPreview, showSymbolPreview, symbolForPreviewCode } from "./symbol-preview.js";

const sequenceRow = document.getElementById("sequence-row");

let socket = null;
let claimedSymbolSet = new Set();
let leftAltDown = false;

const KEYER_MODE_DISPLAY = {
    iambic_a: "Iambic A",
    ultimatic: "Ultimatic",
};

function renderKeyerModeBadge(mode) {
    const el = document.getElementById("key-mode-badge");
    if (!el) return;
    const label = KEYER_MODE_DISPLAY[mode] || (mode ? mode.replace(/_/g, " ") : "—");
    el.textContent = label;
    el.dataset.keyerMode = mode || "";
}

function appendEvent(event) {
    if (event.type === "claimed-symbols") {
        claimedSymbolSet = renderSequence(sequenceRow, event);
        return;
    }
    if (event.type === "audio-settings") {
        renderKeyerModeBadge(event.keyer_mode);
        return;
    }
    if (event.type === "morse-repeat-start") {
        setSequenceTokenPlaying(sequenceRow, event.symbol, true);
        return;
    }
    if (event.type === "morse-repeat-end") {
        setSequenceTokenPlaying(sequenceRow, event.symbol, false);
        hideSymbolPreview();
    }
}

window.addEventListener("keydown", (event) => {
    if (event.code === "AltLeft") {
        leftAltDown = true;
        return;
    }
    if (!leftAltDown || !event.altKey) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
    }
    const symbol = symbolForPreviewCode(event.code, event.shiftKey);
    if (!symbol || !claimedSymbolSet.has(symbol)) return;
    event.preventDefault();
    if (event.repeat) return;
    showSymbolPreview(symbol);
    socket.send(JSON.stringify({ action: "play-morse-repeat", symbol }));
});

window.addEventListener("keyup", (event) => {
    if (event.code === "AltLeft") {
        leftAltDown = false;
    }
});

window.addEventListener("blur", () => {
    leftAltDown = false;
    hideSymbolPreview();
});

installClaimHandlers(sequenceRow, () => socket);
socket = connectKoch({
    onOpen() {
        socket.send(JSON.stringify({ action: "get-audio-settings" }));
    },
    onMessage: appendEvent,
    onClose() {
        hideSymbolPreview();
    },
});
