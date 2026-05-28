// Copy — Symbol Recognition UI.
//
// Connects to the engine, renders the claimed symbol set, and drives
// recognition training sessions. The training flow is entirely
// audio — the learner does not interact with the screen once a
// session starts. Truth is disclosed after session-end.

import {
    clearCountdown as clearCountdownCore,
    connectKoch,
    installClaimHandlers,
    renderSequence,
    setSequenceTokenPlaying,
    startCountdown,
} from "./koch-core.js";

const sequenceRow  = document.getElementById("sequence-row");
const startBtn     = document.getElementById("start");
const countdownEl  = document.getElementById("countdown");
const primedTextEl = document.getElementById("primed-text");
const primedSetEl  = document.getElementById("primed-set");
const eventsEl     = document.getElementById("events");
const answersEl    = document.getElementById("answers");
const saveBtn      = document.getElementById("save-answers");
const toggleBtn    = document.querySelector(".timeline-toggle");
const timelineBody = document.querySelector(".timeline-body");

const COUNTDOWN_SECONDS = 5;
const SET_SIZE = 8;
const VOICE_SAMPLE_RATE = 16_000;

let socket = null;
let countdownTimer = null;
let claimedState = { symbols: [], suggested_next: null, set_is_fresh: true };
let sessionActive = false;
let currentExercises = [];
let currentExerciseIndex = 0;
let currentSetSession = 0;
let voiceReady = false;
let voiceStatusMessage = "Checking voice configuration…";

// Per-exercise buffer of Vosk final events captured during the session.
// Each entry: { t: seconds since session-start, text: raw transcript,
// symbols: tokenised list }. Sent verbatim in save-recognition-answers
// so the session record carries both what Vosk heard and what the
// learner committed — phase 5.1's "two recognitions" diagnostic.
let voiceCapture = [];
let sessionStartMs = 0;

const voice = {
    ws: null,
    ctx: null,
    stream: null,
    node: null,
    running: false,
    session: null,
};

// ─── Primed ──────────────────────────────────────────────────────────────────

function renderPrimed() {
    if (!claimedState.symbols.length) {
        primedTextEl.textContent = "Primed: nothing — claim a symbol first";
        primedSetEl.textContent = "";
        return;
    }
    primedTextEl.textContent =
        `Recognition: ${claimedState.symbols.join(", ")}`;
    primedSetEl.textContent = currentSetSession > 0
        ? `Set ${currentSetSession} of ${SET_SIZE}`
        : "";
}

// ─── Timeline disclosure ─────────────────────────────────────────────────────

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

setTimelineOpen(false);
setTimelineLocked(true);

// ─── Voice readiness ─────────────────────────────────────────────────────────

// Voice is a precondition for this page. If [voice] isn't configured or
// the model/vosk aren't ready, Start stays disabled and a single notice
// near the controls names the reason. The user fixes it in Settings →
// Voice; on reload the check re-runs.
async function refreshVoiceReady() {
    try {
        const res = await fetch("/api/voice/status", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        voiceReady = !!data.ready;
        if (voiceReady) {
            voiceStatusMessage = "";
        } else if (!data.model_path) {
            voiceStatusMessage = "Voice not configured — see Settings → Voice.";
        } else if (!data.model_exists) {
            voiceStatusMessage = `Voice model not found at ${data.model_path_resolved}.`;
        } else if (!data.vosk_installed) {
            voiceStatusMessage = "vosk not installed — pip install -e \".[voice]\".";
        } else {
            voiceStatusMessage = "Voice not ready.";
        }
    } catch (err) {
        voiceReady = false;
        voiceStatusMessage = `Voice status check failed: ${err.message}`;
    }
    renderVoiceNotice();
    if (startBtn.dataset.mode === "idle") setStartButtonMode("idle");
}

function renderVoiceNotice() {
    let notice = document.getElementById("voice-notice");
    if (voiceReady) {
        if (notice) notice.remove();
        return;
    }
    if (!notice) {
        notice = document.createElement("p");
        notice.id = "voice-notice";
        notice.className = "voice-notice";
        startBtn.parentElement.appendChild(notice);
    }
    notice.textContent = voiceStatusMessage;
}

// ─── Voice capture lifecycle ─────────────────────────────────────────────────

async function startVoiceCapture() {
    const session = Symbol("voice-session");
    voice.session = session;

    const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/voice/ws`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    voice.ws = ws;

    const ready = new Promise((resolve, reject) => {
        const onMsg = (ev) => {
            let msg;
            try { msg = JSON.parse(ev.data); } catch { return; }
            if (msg.type === "ready") {
                ws.removeEventListener("message", onMsg);
                resolve();
            } else if (msg.type === "error") {
                ws.removeEventListener("message", onMsg);
                reject(new Error(msg.message || msg.reason || "voice error"));
            }
        };
        ws.addEventListener("message", onMsg);
    });

    ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (voice.session !== session) return;
        if (msg.type === "final") {
            const symbols = Array.isArray(msg.symbols) ? msg.symbols : [];
            recordVoiceFinal(msg.text || "", symbols);
            if (symbols.length) appendSymbolsToActiveRow(symbols);
        }
    };
    ws.onclose = () => { if (voice.session === session) stopVoiceCapture(); };

    await new Promise((resolve, reject) => {
        ws.addEventListener("open", resolve, { once: true });
        ws.addEventListener("error", reject, { once: true });
    });
    if (voice.session !== session) return;

    await ready;
    if (voice.session !== session) return;

    const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
            channelCount: 1,
            sampleRate: VOICE_SAMPLE_RATE,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
        },
    });
    if (voice.session !== session) { stream.getTracks().forEach((t) => t.stop()); return; }
    voice.stream = stream;

    const ctx = new AudioContext({ sampleRate: VOICE_SAMPLE_RATE });
    voice.ctx = ctx;
    await ctx.audioWorklet.addModule("../js/voice-recorder-worklet.js");
    if (voice.session !== session) { try { ctx.close(); } catch {} return; }

    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, "voice-recorder-processor");
    voice.node = node;

    node.port.onmessage = (ev) => {
        if (ws.readyState !== WebSocket.OPEN) return;
        const pcm = floatTo16BitPCM(ev.data.pcm);
        ws.send(pcm.buffer);
    };

    source.connect(node);
    // Intentionally not connecting to ctx.destination.

    voice.running = true;
}

function stopVoiceCapture() {
    voice.running = false;
    voice.session = null;
    if (voice.node) { try { voice.node.disconnect(); } catch {} voice.node = null; }
    if (voice.ctx)  { try { voice.ctx.close();      } catch {} voice.ctx = null; }
    if (voice.stream) {
        voice.stream.getTracks().forEach((t) => t.stop());
        voice.stream = null;
    }
    if (voice.ws) { try { voice.ws.close(); } catch {} voice.ws = null; }
}

function floatTo16BitPCM(input) {
    const out = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) {
        const s = Math.max(-1, Math.min(1, input[i]));
        out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return out;
}

// ─── Answers table ───────────────────────────────────────────────────────────

function renderAnswerRows(exerciseCount) {
    answersEl.replaceChildren();
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    const blank = document.createElement("th");
    blank.scope = "col";
    blank.className = "answers-table__corner";
    const heading = document.createElement("th");
    heading.scope = "col";
    heading.textContent = "Your answer";
    headRow.append(blank, heading);
    thead.appendChild(headRow);

    const tbody = document.createElement("tbody");
    for (let i = 1; i <= exerciseCount; i++) {
        const tr = document.createElement("tr");
        tr.dataset.exerciseIndex = String(i);
        const th = document.createElement("th");
        th.scope = "row";
        th.textContent = String(i);
        const td = document.createElement("td");
        const input = document.createElement("input");
        input.type = "text";
        input.className = "answer-row__input";
        input.dataset.exerciseIndex = String(i);
        input.readOnly = true;  // unlocked at session-end
        input.autocomplete = "off";
        input.spellcheck = false;
        td.appendChild(input);
        tr.append(th, td);
        tbody.appendChild(tr);
    }

    answersEl.append(thead, tbody);
}

function setActiveRow(exerciseIndex) {
    answersEl.querySelectorAll("tr[data-exercise-index]").forEach((tr) => {
        const isActive = tr.dataset.exerciseIndex === String(exerciseIndex);
        tr.classList.toggle("answer-row--active", isActive);
    });
}

function appendSymbolsToActiveRow(symbols) {
    if (!currentExerciseIndex) return;
    const input = answersEl.querySelector(
        `.answer-row__input[data-exercise-index="${currentExerciseIndex}"]`,
    );
    if (!input) return;
    input.value = input.value + symbols.join("");
}

// Push a Vosk final into the per-exercise capture buffer and render it
// on the Truth view next to engine symbols. Events that arrive before
// the first engine symbol fires (active index still 0) attach to the
// first exercise's bucket — Vosk can fire mid-countdown if the user
// speaks early, and dropping those entirely would hide an interesting
// timing failure.
function recordVoiceFinal(text, symbols) {
    const exerciseIdx = Math.max(1, currentExerciseIndex);
    const tSeconds = (performance.now() - sessionStartMs) / 1000;
    const entry = { t: round4(tSeconds), text: text, symbols: Array.from(symbols) };
    while (voiceCapture.length < exerciseIdx) voiceCapture.push([]);
    voiceCapture[exerciseIdx - 1].push(entry);
    renderVoiceEvent(entry);
}

function round4(n) {
    return Math.round(n * 10000) / 10000;
}

function renderVoiceEvent(entry) {
    const li = document.createElement("li");
    li.dataset.kind = "voice";
    li.dataset.exerciseIndex = String(Math.max(1, currentExerciseIndex));
    const time = document.createElement("span");
    time.className = "events-time";
    time.textContent = `${entry.t.toFixed(2)}s`;
    const arrow = document.createElement("span");
    arrow.className = "events-voice-text";
    arrow.textContent = entry.symbols.length
        ? `${entry.text} → ${entry.symbols.join("")}`
        : `${entry.text} → —`;
    li.append(time, arrow);
    eventsEl.appendChild(li);
}

function unlockAnswerInputs() {
    answersEl.querySelectorAll(".answer-row__input").forEach((input) => {
        input.readOnly = false;
    });
    answersEl.querySelectorAll("tr[data-exercise-index]").forEach((tr) => {
        tr.classList.remove("answer-row--active");
    });
}

function collectAnswers() {
    return Array.from(
        answersEl.querySelectorAll(".answer-row__input"),
        (input) => input.value,
    );
}

// ─── Controls ────────────────────────────────────────────────────────────────

function clearCountdown() {
    clearCountdownCore(countdownEl, countdownTimer);
    countdownTimer = null;
}

function setStartButtonMode(mode) {
    startBtn.dataset.mode = mode;
    if (mode === "idle") {
        clearCountdown();
        const wsReady = socket && socket.readyState === WebSocket.OPEN;
        startBtn.disabled = !wsReady || !voiceReady;
        startBtn.innerHTML = "<u>S</u>tart";
    } else if (mode === "counting") {
        startBtn.disabled = false;
        startBtn.textContent = "Cancel";
    } else if (mode === "active") {
        clearCountdown();
        startBtn.disabled = false;
        startBtn.textContent = "Abort";
    } else if (mode === "end") {
        clearCountdown();
        startBtn.disabled = false;
        startBtn.textContent = "End";
    }
}

function beginCountdownThenStart() {
    eventsEl.replaceChildren();
    const meta = toggleBtn.querySelector(".timeline-meta");
    meta.textContent = "—";
    setTimelineOpen(false);
    setTimelineLocked(true);

    countdownTimer = startCountdown(countdownEl, startBtn, COUNTDOWN_SECONDS, () => {
        countdownTimer = null;
        if (!socket || socket.readyState !== WebSocket.OPEN) {
            setStartButtonMode("idle");
            return;
        }
        socket.send(JSON.stringify({ action: "start-recognition" }));
        startBtn.disabled = true;
    });
}

startBtn.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const mode = startBtn.dataset.mode;
    if (mode === "active") {
        socket.send(JSON.stringify({ action: "stop" }));
        startBtn.disabled = true;
        return;
    }
    if (mode === "counting") {
        setStartButtonMode("idle");
        return;
    }
    if (mode === "end") {
        currentSetSession = 0;
        eventsEl.replaceChildren();
        setStartButtonMode("idle");
        renderPrimed();
        return;
    }
    beginCountdownThenStart();
});

// ─── Start keybind (S) ──────────────────────────────────────────────────────

window.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
    }
    if (event.key.toLowerCase() !== "s") return;
    if (startBtn.disabled) return;
    event.preventDefault();
    startBtn.click();
});

// ─── Event handling ──────────────────────────────────────────────────────────

function appendEvent(event) {
    if (event.type === "claimed-symbols") {
        claimedState = event;
        renderSequence(sequenceRow, event);
        renderPrimed();
        return;
    }
    if (event.type === "morse-repeat-start") {
        setSequenceTokenPlaying(sequenceRow, event.symbol, true);
        return;
    }
    if (event.type === "morse-repeat-end") {
        setSequenceTokenPlaying(sequenceRow, event.symbol, false);
        return;
    }

    if (event.type === "session-start") {
        currentExercises = Array.isArray(event.exercises) ? event.exercises : [];
        currentExerciseIndex = 0;
        currentSetSession = event.set_session || 0;
        sessionActive = true;
        sessionStartMs = performance.now();
        voiceCapture = currentExercises.map(() => []);
        setStartButtonMode("active");
        const meta = toggleBtn.querySelector(".timeline-meta");
        meta.textContent = `seed ${event.seed} · ${currentExercises.length} exercises`;
        // Lock the Truth panel only — the Answers panel is visible
        // during the session so the learner can watch their voice
        // capture fill the active row. Truth stays hidden until
        // session-end (spec §9 — no real-time correctness feedback).
        setTimelineLocked(true);
        setTimelineOpen(true);
        setActiveTab("answers");
        eventsEl.replaceChildren();
        renderAnswerRows(currentExercises.length);
        saveBtn.disabled = true;
        primedTextEl.textContent = `Exercise — of ${currentExercises.length}`;
        primedSetEl.textContent = currentSetSession > 0
            ? `Set ${currentSetSession} of ${SET_SIZE}`
            : "";
        // Open voice capture in the background. If it fails the
        // session continues (the page is degraded but not broken);
        // the failure surfaces in the timeline events log.
        startVoiceCapture().catch((err) => {
            const li = document.createElement("li");
            li.textContent = `! voice: ${err.message || err}`;
            li.dataset.kind = "error";
            eventsEl.appendChild(li);
        });
        return;
    }

    if (event.type === "symbol") {
        if (event.exercise_index !== currentExerciseIndex) {
            if (currentExerciseIndex !== 0) {
                const divider = document.createElement("li");
                divider.dataset.kind = "exercise-divider";
                divider.appendChild(document.createElement("hr"));
                eventsEl.appendChild(divider);
            }
            currentExerciseIndex = event.exercise_index;
            setActiveRow(currentExerciseIndex);
            const header = document.createElement("li");
            header.dataset.kind = "exercise-header";
            const exerciseString = currentExercises[event.exercise_index - 1] || "";
            header.textContent = `Exercise ${event.exercise_index}: ${exerciseString}`;
            eventsEl.appendChild(header);
            primedTextEl.textContent =
                `Exercise ${currentExerciseIndex} of ${currentExercises.length}`;
        }
        const li = document.createElement("li");
        li.dataset.kind = "symbol";
        li.dataset.exerciseIndex = String(event.exercise_index);
        if (typeof event.t_on === "number") {
            const time = document.createElement("span");
            time.className = "events-time";
            time.textContent = `${event.t_on.toFixed(2)}s`;
            const sym = document.createElement("span");
            sym.className = "events-symbol";
            sym.textContent = event.symbol;
            li.append(time, sym);
        } else {
            li.textContent = event.symbol;
        }
        eventsEl.appendChild(li);
        return;
    }

    if (event.type === "session-end") {
        sessionActive = false;
        stopVoiceCapture();
        unlockAnswerInputs();
        saveBtn.disabled = false;
        saveBtn.dataset.state = "ready";
        const li = document.createElement("li");
        li.textContent = "■ end";
        li.dataset.kind = "end";
        eventsEl.appendChild(li);
        setStartButtonMode(currentSetSession >= SET_SIZE ? "end" : "idle");
        setTimelineLocked(false);
        renderPrimed();
        return;
    }

    if (event.type === "recognition-answers-saved") {
        saveBtn.disabled = true;
        saveBtn.dataset.state = "saved";
        saveBtn.textContent = "Saved";
        return;
    }

    if (event.type === "error") {
        const detail = event.detail ? `: ${event.detail}` : "";
        const li = document.createElement("li");
        li.textContent = `! ${event.reason}${detail}`;
        li.dataset.kind = "error";
        eventsEl.appendChild(li);
        setStartButtonMode("idle");
        sessionActive = false;
        stopVoiceCapture();
        setTimelineLocked(false);
        return;
    }
}

// ─── Timeline tab switching ──────────────────────────────────────────────────

const tabButtons = document.querySelectorAll(".timeline-tab");
function setActiveTab(name) {
    tabButtons.forEach((btn) => {
        const selected = btn.dataset.tab === name;
        btn.dataset.selected = selected ? "true" : "false";
        btn.setAttribute("aria-selected", selected ? "true" : "false");
        const panelId = btn.getAttribute("aria-controls");
        if (panelId) {
            const panel = document.getElementById(panelId);
            if (panel) panel.hidden = !selected;
        }
    });
}
tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => setActiveTab(btn.dataset.tab));
});

// ─── Save button ─────────────────────────────────────────────────────────────

saveBtn.addEventListener("click", () => {
    if (saveBtn.disabled) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    saveBtn.disabled = true;
    socket.send(JSON.stringify({
        action: "save-recognition-answers",
        answers: collectAnswers(),
        voice_capture: voiceCapture,
    }));
});

// Allow re-saving after edits.
answersEl.addEventListener("input", (event) => {
    if (!(event.target instanceof HTMLInputElement)) return;
    if (saveBtn.dataset.state === "saved") {
        saveBtn.dataset.state = "ready";
        saveBtn.disabled = false;
        saveBtn.textContent = "Save";
    }
});

// ─── Init ────────────────────────────────────────────────────────────────────

installClaimHandlers(sequenceRow, () => socket, () => sessionActive);
socket = connectKoch({
    onOpen() { setStartButtonMode("idle"); },
    onMessage: appendEvent,
    onClose() {
        clearCountdown();
        startBtn.disabled = true;
        sessionActive = false;
        stopVoiceCapture();
        setTimelineLocked(false);
    },
});

refreshVoiceReady();
