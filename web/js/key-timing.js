// Copy — Key timing page entry.
//
// Slim orchestrator: wires up the per-concern modules under
// ./key-timing/, owns the WebSocket connection lifecycle, and binds
// the page-level keyboard shortcuts and the symbol-preview keydown
// handler. Every other concern lives in its own module.

import "./developer-mode.js";
import { makeAccelLabel } from "./key-timing/utils.js";
import {
    clearSentEl,
    copyDiagnosticsEl,
    copyHistoryEl,
    copyHistoryToggleEl,
    keyInputToggleEl,
    newSetEl,
    rhythmReviewToggleEl,
    sequenceRow,
    statusEl,
} from "./key-timing/dom.js";
import {
    isSoundEnabled,
    sidetone,
    toggleSidetone,
    updateAudioDiagnostic,
} from "./key-timing/sidetone.js";
import {
    renderCopyHistoryToggleLabel,
    renderKeyPageActionsToggleLabel,
    renderRhythmReviewToggleLabel,
    renderSentToggleLabel,
    renderSequenceToggleLabel,
    setCopyHistoryExpanded,
    setRhythmReviewExpanded,
    toggleCopyHistory,
    toggleKeyPageActions,
    toggleRhythmReview,
    toggleSent,
    toggleSequence,
} from "./key-timing/collapsibles.js";
import {
    diagnosticText,
    installDiagnosticsAccessors,
    recordDiagnostic,
} from "./key-timing/diagnostics.js";
import {
    installReviewAccessors,
    renderRhythmReview,
} from "./key-timing/review.js";
import {
    buildSequenceRow,
    claimedSymbolHas,
    renderSequence,
    setSequenceTokenPlaying,
} from "./key-timing/sequence-row.js";
import {
    clearSentSymbols,
    getCopyExercises,
    getSentEventsByExercise,
    installCopyProgressAccessors,
    renderCopyExercises,
    renderSentSymbol,
    requestCopyExercises,
    selectCopyExercise,
} from "./key-timing/copy-progress.js";
import {
    appendDiagnosticRow,
    clearBrowserMidiInput,
    getKeyConfig,
    getMidiInputArmed,
    installMidiInputAccessors,
    renderError,
    renderKeyEvent,
    renderKeyInputReset,
    renderKeyInputStart,
    setMidiInputArmed,
    startBrowserMidi,
} from "./key-timing/midi-input.js";

const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
const wsUrl = `${wsProtocol}//${location.host}/ws`;

let activeSocket = null;
// Left-Alt held state, tracked via event.code so we can scope the
// Cadence preview keybind to LeftAlt only (not RightAlt). Reset on
// blur because the matching keyup may never arrive if focus is lost.
let leftAltDown = false;

function setStatus(state, text) {
    statusEl.dataset.status = state;
    statusEl.textContent = text;
}

installCopyProgressAccessors({
    activeSocket: () => activeSocket,
    keyConfig: getKeyConfig,
    appendDiagnosticRow,
});
installMidiInputAccessors({ setStatus });
installDiagnosticsAccessors({
    keyConfig: getKeyConfig,
    midiInputArmed: getMidiInputArmed,
});
installReviewAccessors({
    exercises: getCopyExercises,
    sentEvents: getSentEventsByExercise,
    keyConfig: getKeyConfig,
});

function renderClearSentLabel() {
    clearSentEl.replaceChildren(makeAccelLabel("c", "lear"));
    clearSentEl.title = "Clear sent symbols (C)";
    clearSentEl.setAttribute("aria-keyshortcuts", "C");
}

function renderNewSetLabel() {
    if (!newSetEl) return;
    newSetEl.replaceChildren(makeAccelLabel("n", "ew"));
    newSetEl.title = "New exercise set (N)";
    newSetEl.setAttribute("aria-keyshortcuts", "N");
}

function connect() {
    setStatus("connecting", "connecting...");
    const socket = new WebSocket(wsUrl);
    activeSocket = socket;

    socket.addEventListener("open", () => {
        recordDiagnostic("websocket", { state: "open", url: wsUrl });
        setStatus("connected", "connected");
        startBrowserMidi(socket);
    });

    socket.addEventListener("message", (message) => {
        const event = JSON.parse(message.data);
        if (event.type === "claimed-symbols") {
            renderSequence(event);
            // Cadence page only — refresh exercises when the claimed
            // set changes.
            requestCopyExercises();
        } else if (event.type === "copy-exercises") {
            renderCopyExercises(event);
        } else if (event.type === "sent-symbol") {
            renderSentSymbol(event);
        } else if (event.type === "key-input-start") {
            renderKeyInputStart(event);
        } else if (event.type === "key-event") {
            renderKeyEvent(event);
        } else if (event.type === "key-input-reset") {
            renderKeyInputReset(event);
        } else if (event.type === "morse-repeat-start") {
            setSequenceTokenPlaying(event.symbol, true);
        } else if (event.type === "morse-repeat-end") {
            setSequenceTokenPlaying(event.symbol, false);
        } else if (event.type === "error") {
            renderError(event);
        }
    });

    socket.addEventListener("close", () => {
        recordDiagnostic("websocket", { state: "close", url: wsUrl });
        setSequenceTokenPlaying(null, false);
        sidetone.mute();
        clearBrowserMidiInput();
        if (activeSocket === socket) {
            activeSocket = null;
        }
        setStatus("connecting", "disconnected");
    });
}

buildSequenceRow();
document.addEventListener("visibilitychange", () => {
    recordDiagnostic("page-lifecycle", {
        event: "visibilitychange",
        visibility: document.visibilityState,
    });
    if (document.visibilityState === "hidden") {
        setMidiInputArmed(false, "page hidden");
    } else if (document.visibilityState === "visible" && !getMidiInputArmed()) {
        setMidiInputArmed(true, "page visible");
    }
});
keyInputToggleEl.addEventListener("click", () => {
    setMidiInputArmed(!getMidiInputArmed(), "manual toggle");
});
copyDiagnosticsEl.addEventListener("click", async () => {
    const previousText = copyDiagnosticsEl.textContent;
    const text = diagnosticText();
    try {
        await navigator.clipboard.writeText(text);
        copyDiagnosticsEl.textContent = "copied";
        recordDiagnostic("diagnostics-copy", { status: "clipboard", bytes: text.length });
    } catch {
        window.prompt("Copy diagnostics", text);
        copyDiagnosticsEl.textContent = "copy shown";
        recordDiagnostic("diagnostics-copy", { status: "prompt", bytes: text.length });
    }
    window.setTimeout(() => {
        copyDiagnosticsEl.textContent = previousText;
    }, 1200);
});
clearSentEl.addEventListener("click", clearSentSymbols);
if (newSetEl) newSetEl.addEventListener("click", requestCopyExercises);
if (rhythmReviewToggleEl) {
    rhythmReviewToggleEl.addEventListener("click", () => {
        const expanded = rhythmReviewToggleEl.getAttribute("aria-expanded") === "true";
        setRhythmReviewExpanded(!expanded);
    });
}
if (copyHistoryToggleEl) {
    copyHistoryToggleEl.addEventListener("click", () => {
        const expanded = copyHistoryToggleEl.getAttribute("aria-expanded") === "true";
        setCopyHistoryExpanded(!expanded);
    });
}

// Key-page preview: Left Alt + symbol-key plays the symbol's bare
// Morse three times through the engine output. event.code is used
// because Option+letter on macOS substitutes characters in event.key.
// Scoped to pages that render the Sequence grid (Cadence + Freeplay)
// via sequenceRow.
const PREVIEW_CODE_TO_SYMBOL = (() => {
    const map = new Map();
    for (let i = 0; i < 26; i++) {
        map.set(`Key${String.fromCharCode(65 + i)}`, String.fromCharCode(65 + i));
    }
    for (let i = 0; i <= 9; i++) {
        map.set(`Digit${i}`, String(i));
    }
    map.set("Period", ".");
    map.set("Comma", ",");
    map.set("Equal", "=");
    return map;
})();

function symbolForPreviewCode(code, shiftKey) {
    if (code === "Slash") return shiftKey ? "?" : "/";
    return PREVIEW_CODE_TO_SYMBOL.get(code) || null;
}

window.addEventListener("keydown", (event) => {
    if (event.code === "AltLeft") {
        leftAltDown = true;
        return;
    }
    if (!leftAltDown || !event.altKey) return;
    if (!sequenceRow) return;
    if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
    }
    const symbol = symbolForPreviewCode(event.code, event.shiftKey);
    if (!symbol) return;
    // Freeplay (no Copy section) opens up every symbol for preview;
    // Cadence still gates on the claimed set so the preview matches
    // the curriculum the Copy exercise is drawing from.
    if (copyHistoryEl && !claimedSymbolHas(symbol)) return;
    event.preventDefault();
    if (event.repeat) return;
    activeSocket.send(JSON.stringify({ action: "play-morse-repeat", symbol }));
});

window.addEventListener("keyup", (event) => {
    if (event.code === "AltLeft") {
        leftAltDown = false;
    }
});

window.addEventListener("blur", () => {
    leftAltDown = false;
});

window.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
    }
    const key = event.key.toLowerCase();
    if (isSoundEnabled() && key === "m") {
        event.preventDefault();
        toggleSidetone();
    } else if (!isSoundEnabled() && key === "s") {
        event.preventDefault();
        toggleSidetone();
    } else if (key === "c") {
        event.preventDefault();
        clearSentSymbols();
    } else if (key === "n") {
        event.preventDefault();
        requestCopyExercises();
    } else if (key === "e") {
        event.preventDefault();
        toggleCopyHistory();
    } else if (key === "r") {
        event.preventDefault();
        toggleRhythmReview();
    } else if (key === "q") {
        event.preventDefault();
        toggleSequence();
    } else if (key === "t") {
        event.preventDefault();
        toggleKeyPageActions();
    } else if (key === "x") {
        event.preventDefault();
        toggleSent();
    } else if (/^[1-9]$/.test(key)) {
        if (selectCopyExercise(parseInt(key, 10) - 1)) {
            event.preventDefault();
        }
    }
});
renderClearSentLabel();
renderNewSetLabel();
renderCopyHistoryToggleLabel();
renderRhythmReviewToggleLabel();
renderSequenceToggleLabel();
renderKeyPageActionsToggleLabel();
renderSentToggleLabel();
renderRhythmReview();
updateAudioDiagnostic();
connect();
