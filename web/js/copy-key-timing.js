// Copy — Copy Key page entry.
//
// Orchestrates the Copy Key (hear-hold-send) exercise flow. Reuses
// the shared key-timing modules for sequence row, sidetone, MIDI
// input, diagnostics, and rhythm review. The exercise lifecycle is
// unique to this page: the server plays audio for one exercise at a
// time, the learner head-copies and keys it back, then the next
// exercise plays.

import "./developer-mode.js";
import { makeAccelLabel } from "./key-timing/utils.js";
import {
    clearSentEl,
    copyDiagnosticsEl,
    keyInputToggleEl,
    newSetEl,
    rhythmReviewToggleEl,
    sentHistoryEl,
    sentSymbolEl,
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
    renderRhythmReviewToggleLabel,
    renderSentToggleLabel,
    renderSequenceToggleLabel,
    renderKeyPageActionsToggleLabel,
    setRhythmReviewExpanded,
    toggleRhythmReview,
    toggleSent,
    toggleSequence,
    toggleKeyPageActions,
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
    claimedSymbolHas,
    renderSequence,
    setSequenceTokenPlaying,
} from "./key-timing/sequence-row.js";
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
import { initTrinkeySyncIndicator } from "./key-timing/trinkey-sync-indicator.js";

const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
const wsUrl = `${wsProtocol}//${location.host}/ws`;

const startBtn = document.getElementById("start");
const countdownEl = document.getElementById("countdown");
const primedEl = document.getElementById("primed");

const EXERCISE_COUNT = 5;
const COUNTDOWN_SECONDS = 5;

let activeSocket = null;
let leftAltDown = false;
let countdownTimer = null;
let claimedState = { symbols: [], suggested_next: null };
let exercises = [];
let sessionActive = false;
let currentExerciseIndex = 0;
let exercisePlaying = false;
let advanceTimer = null;
let lastSentSymbol = "";

// Sent tracking — per-exercise buckets for the rhythm review.
let sentByExercise = [];
const MAX_SENT_HISTORY = 48;
let sentCount = 0;

const ADVANCE_DELAY_MS = 2000;

const KEYER_MODE_DISPLAY = {
    iambic_a: "Iambic A",
    ultimatic: "Ultimatic",
};

function setStatus(state, text) {
    statusEl.dataset.status = state;
    statusEl.textContent = text;
}

function renderKeyerModeBadge(mode) {
    const el = document.getElementById("key-mode-badge");
    if (!el) return;
    const label = KEYER_MODE_DISPLAY[mode] || (mode ? mode.replace(/_/g, " ") : "—");
    el.textContent = label;
    el.dataset.keyerMode = mode || "";
}

function renderPrimed() {
    if (!claimedState.symbols.length) {
        primedEl.textContent = "Primed: —";
        return;
    }
    primedEl.textContent =
        `Primed: ${EXERCISE_COUNT} exercises of ${claimedState.symbols.join(", ")}`;
}

function setStartButtonMode(mode) {
    startBtn.dataset.mode = mode;
    if (mode === "idle") {
        clearCountdown();
        startBtn.disabled = !activeSocket || activeSocket.readyState !== WebSocket.OPEN;
        startBtn.innerHTML = "St<u>a</u>rt";
    } else if (mode === "counting") {
        startBtn.disabled = false;
        startBtn.textContent = "Cancel";
    } else if (mode === "active") {
        clearCountdown();
        startBtn.disabled = false;
        startBtn.innerHTML = "A<u>b</u>ort";
    }
}

function clearCountdown() {
    if (countdownTimer !== null) {
        clearInterval(countdownTimer);
        countdownTimer = null;
    }
    countdownEl.hidden = true;
    countdownEl.textContent = "";
}

function beginCountdownThenStart() {
    if (!isSoundEnabled()) {
        toggleSidetone();
    }
    let remaining = COUNTDOWN_SECONDS;
    countdownEl.hidden = false;
    countdownEl.textContent = String(remaining);
    setStartButtonMode("counting");

    countdownTimer = setInterval(() => {
        remaining -= 1;
        if (remaining > 0) {
            countdownEl.textContent = String(remaining);
            return;
        }
        clearInterval(countdownTimer);
        countdownTimer = null;
        countdownEl.hidden = true;
        countdownEl.textContent = "";
        if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) {
            setStartButtonMode("idle");
            return;
        }
        activeSocket.send(JSON.stringify({ action: "request-copy-key-exercises" }));
        startBtn.disabled = true;
    }, 1000);
}

function clearSentSymbols() {
    sentSymbolEl.textContent = "";
    sentHistoryEl.replaceChildren();
    sentCount = 0;
}

function clearAdvanceTimer() {
    if (advanceTimer !== null) {
        clearTimeout(advanceTimer);
        advanceTimer = null;
    }
}

function renderSentSymbol(event) {
    if (!event.symbol) return;

    // TODO: IMI detection (I M I) — replay the current exercise audio
    // so the learner gets a second listen without advancing. Strip I M I
    // from the exercise record the same way BK is stripped below.

    // BK detection: B immediately followed by K signals "go ahead."
    // Strip both from the exercise record and advance after a pause.
    if (event.symbol === "K" && lastSentSymbol === "B") {
        lastSentSymbol = "";
        // Remove the B that was already pushed to the exercise bucket.
        if (currentExerciseIndex > 0 && currentExerciseIndex <= sentByExercise.length) {
            const bucket = sentByExercise[currentExerciseIndex - 1];
            if (bucket.length > 0 && bucket[bucket.length - 1].symbol === "B") {
                bucket.pop();
            }
        }
        // Remove the B from the sent history display.
        if (sentHistoryEl.lastChild) {
            sentHistoryEl.removeChild(sentHistoryEl.lastChild);
        }
        sentSymbolEl.textContent = "BK";
        primedEl.textContent = exercisePlaying
            ? `Exercise ${currentExerciseIndex} of ${exercises.length}`
            : `BK — next in ${(ADVANCE_DELAY_MS / 1000).toFixed(0)}s`;
        clearAdvanceTimer();
        advanceTimer = setTimeout(() => {
            advanceTimer = null;
            playNextExercise();
        }, ADVANCE_DELAY_MS);
        return;
    }

    lastSentSymbol = event.symbol;
    sentSymbolEl.textContent = event.symbol;
    sentCount++;
    const li = document.createElement("li");
    const leading = event.leading_gap || "none";
    li.classList.add(`key-sent-history__item--leading-${leading}`);
    const symbolEl = document.createElement("span");
    symbolEl.className = "key-sent-history__symbol";
    symbolEl.textContent = event.symbol;
    li.append(symbolEl);
    sentHistoryEl.appendChild(li);
    while (sentHistoryEl.children.length > MAX_SENT_HISTORY) {
        sentHistoryEl.firstElementChild.remove();
    }
    if (currentExerciseIndex > 0 && currentExerciseIndex <= sentByExercise.length) {
        sentByExercise[currentExerciseIndex - 1].push(event);
    }
    renderRhythmReview();
}

function onCopyKeyExercises(event) {
    exercises = event.exercises || [];
    sentByExercise = exercises.map(() => []);
    currentExerciseIndex = 0;
    sessionActive = true;
    lastSentSymbol = "";
    clearAdvanceTimer();
    setStartButtonMode("active");
    clearSentSymbols();
    primedEl.textContent = `Exercise — of ${exercises.length}`;
    playNextExercise();
}

function playNextExercise() {
    lastSentSymbol = "";
    currentExerciseIndex++;
    if (currentExerciseIndex > exercises.length) {
        endSession();
        return;
    }
    primedEl.textContent = `Exercise ${currentExerciseIndex} of ${exercises.length}`;
    if (activeSocket && activeSocket.readyState === WebSocket.OPEN) {
        activeSocket.send(JSON.stringify({
            action: "play-copy-key-exercise",
            exercise_index: currentExerciseIndex,
        }));
    }
}

function endSession() {
    sessionActive = false;
    exercisePlaying = false;
    lastSentSymbol = "";
    clearAdvanceTimer();
    if (activeSocket && activeSocket.readyState === WebSocket.OPEN) {
        activeSocket.send(JSON.stringify({ action: "complete-copy-key-session" }));
    }
    primedEl.textContent = `Complete — ${exercises.length} exercises`;
    setStartButtonMode("idle");
}

function abortSession() {
    sessionActive = false;
    exercisePlaying = false;
    lastSentSymbol = "";
    clearAdvanceTimer();
    if (activeSocket && activeSocket.readyState === WebSocket.OPEN) {
        activeSocket.send(JSON.stringify({ action: "abort-copy-key-session" }));
    }
    primedEl.textContent = `Aborted`;
    setStartButtonMode("idle");
}

// Accessors for shared modules that need page-level state.
installMidiInputAccessors({ setStatus });
installDiagnosticsAccessors({
    keyConfig: getKeyConfig,
    midiInputArmed: getMidiInputArmed,
});
installReviewAccessors({
    exercises: () => exercises,
    sentEvents: () => sentByExercise,
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

function requestNewSet() {
    if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) return;
    if (sessionActive) return;
    beginCountdownThenStart();
}

function connect() {
    setStatus("connecting", "connecting...");
    const socket = new WebSocket(wsUrl);
    activeSocket = socket;

    socket.addEventListener("open", () => {
        recordDiagnostic("websocket", { state: "open", url: wsUrl });
        setStatus("connected", "connected");
        startBrowserMidi(socket);
        if (document.getElementById("key-mode-badge")) {
            socket.send(JSON.stringify({ action: "get-audio-settings" }));
        }
        setStartButtonMode("idle");
    });

    socket.addEventListener("message", (message) => {
        const event = JSON.parse(message.data);
        if (event.type === "claimed-symbols") {
            renderSequence(event);
            claimedState = event;
            renderPrimed();
        } else if (event.type === "copy-key-exercises") {
            onCopyKeyExercises(event);
        } else if (event.type === "copy-key-exercise-start") {
            exercisePlaying = true;
        } else if (event.type === "copy-key-exercise-end") {
            exercisePlaying = false;
        } else if (event.type === "audio-settings") {
            renderKeyerModeBadge(event.keyer_mode);
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
        startBtn.disabled = true;
        sessionActive = false;
        exercisePlaying = false;
        lastSentSymbol = "";
        clearAdvanceTimer();
    });
}

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
if (newSetEl) newSetEl.addEventListener("click", requestNewSet);
if (rhythmReviewToggleEl) {
    rhythmReviewToggleEl.addEventListener("click", () => {
        const expanded = rhythmReviewToggleEl.getAttribute("aria-expanded") === "true";
        setRhythmReviewExpanded(!expanded);
    });
}

startBtn.addEventListener("click", () => {
    if (!activeSocket || activeSocket.readyState !== WebSocket.OPEN) return;
    const mode = startBtn.dataset.mode;
    if (mode === "active") {
        abortSession();
        return;
    }
    if (mode === "counting") {
        setStartButtonMode("idle");
        return;
    }
    beginCountdownThenStart();
});

// Preview: Left Alt + symbol key plays the symbol's Morse three times.
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
    if (!claimedSymbolHas(symbol)) return;
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
        requestNewSet();
    } else if (key === "a") {
        event.preventDefault();
        if (!startBtn.disabled) startBtn.click();
    } else if (key === "b") {
        if (sessionActive) {
            event.preventDefault();
            abortSession();
        }
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
    }
});

renderClearSentLabel();
renderNewSetLabel();
renderRhythmReviewToggleLabel();
renderSequenceToggleLabel();
renderKeyPageActionsToggleLabel();
renderSentToggleLabel();
renderRhythmReview();
updateAudioDiagnostic();
initTrinkeySyncIndicator();
connect();
