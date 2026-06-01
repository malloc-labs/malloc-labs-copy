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
import { voiceInputAudioConstraints } from "./voice-input-device.js";

const sequenceRow  = document.getElementById("sequence-row");
const startBtn     = document.getElementById("start");
const countdownEl  = document.getElementById("countdown");
const primedTextEl = document.getElementById("primed-text");
const primedSetEl  = document.getElementById("primed-set");
const eventsEl     = document.getElementById("events");
const answersEl    = document.getElementById("answers");
const timingTabsEl = document.getElementById("recognition-timing-tabs");
const timingEl     = document.getElementById("recognition-timing");
const saveBtn      = document.getElementById("save-answers");
const toggleBtn    = document.querySelector(".timeline-toggle");
const timelineBody = document.querySelector(".timeline-body");

const COUNTDOWN_SECONDS = 5;
const SET_SIZE = 8;
const VOICE_SAMPLE_RATE = 16_000;
// Exercise completion is deliberately adaptive. A fluent answer should
// keep the training cadence tight, but a slightly slower learner — or a
// slower browser/Vosk final — should not lose an otherwise valid spoken
// answer just because the client saved on a fixed wall-clock tick.
const EXERCISE_COMPLETION_INITIAL_GRACE_MS = 2500;
const EXERCISE_COMPLETION_QUIET_MS = 700;
const EXERCISE_COMPLETION_HARD_CAP_MS = 6000;
const EXERCISE_DIAGNOSTIC_TAIL_MS = 3000;

let socket = null;
let countdownTimer = null;
let claimedState = { symbols: [], suggested_next: null, set_is_fresh: true };
let sessionActive = false;
let currentExercises = [];
let currentExerciseIndex = 0;
let currentSetSession = 0;
let currentRecognitionGear = null;
let currentRecognitionKind = "";
let voiceReady = false;
let voiceStatusMessage = "Checking voice configuration…";
let pendingSaveResolve = null;
let voiceStartPromise = null;
let pendingExerciseCompletion = null;
let lastVoiceFinalByExercise = [];
let diagnosticTail = null;
let symbolEventsByExercise = [];
let selectedTimingExerciseIndex = 1;

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
    primedSetEl.textContent = recognitionSetNotice();
}

function recognitionSetNotice() {
    const parts = [];
    if (currentSetSession > 0) parts.push(`Set ${currentSetSession} of ${SET_SIZE}`);
    const mode = recognitionModeLabel(currentRecognitionGear, currentRecognitionKind);
    if (mode) parts.push(mode);
    return parts.join(" · ");
}

function recognitionModeLabel(gear, kind) {
    if (!Number.isInteger(gear)) return "";
    if (gear <= 0) return "Gear 0: singles, first confirms";
    if (kind === "words") return `Gear ${gear}: words, no confirm`;
    if (kind === "pairs") return `Gear ${gear}: pairs, no confirm`;
    return `Gear ${gear}: no confirm`;
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
    if (voice.running) return;
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
            if (!sessionActive || !currentExercises.length) return;
            const symbols = Array.isArray(msg.symbols) ? msg.symbols : [];
            recordVoiceFinal(msg.text || "", symbols);
            if (symbols.length) appendSymbolsToActiveRow(symbols);
        } else if (msg.type === "partial") {
            if (!sessionActive || !currentExercises.length) return;
            markExerciseVoiceActivity(Math.max(1, currentExerciseIndex));
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

    const stream = await navigator.mediaDevices.getUserMedia(voiceInputAudioConstraints());
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

async function ensureVoiceCaptureReady() {
    if (voice.running) return;
    if (!voiceStartPromise) {
        voiceStartPromise = startVoiceCapture().finally(() => {
            voiceStartPromise = null;
        });
    }
    await voiceStartPromise;
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

function clearPendingExerciseCompletion() {
    if (pendingExerciseCompletion?.timer) {
        window.clearTimeout(pendingExerciseCompletion.timer);
    }
    pendingExerciseCompletion = null;
}

function clearDiagnosticTail() {
    if (diagnosticTail?.timer) {
        window.clearTimeout(diagnosticTail.timer);
    }
    diagnosticTail = null;
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
    const correctHeading = document.createElement("th");
    correctHeading.scope = "col";
    correctHeading.textContent = "Correct";
    headRow.append(blank, heading, correctHeading);
    thead.appendChild(headRow);

    const tbody = document.createElement("tbody");
    for (let i = 1; i <= exerciseCount; i++) {
        const tr = document.createElement("tr");
        tr.dataset.exerciseIndex = String(i);
        const th = document.createElement("th");
        th.scope = "row";
        th.className = "answer-row__label";
        th.textContent = String(i);
        const td = document.createElement("td");
        td.className = "answer-row__cell";
        const input = document.createElement("input");
        input.type = "text";
        input.className = "answer-row__input";
        input.dataset.exerciseIndex = String(i);
        input.readOnly = true;  // unlocked at session-end
        input.autocomplete = "off";
        input.spellcheck = false;
        td.appendChild(input);
        const correctTd = document.createElement("td");
        correctTd.className = "answer-row__sent";
        correctTd.dataset.correctFor = String(i);
        tr.append(th, td, correctTd);
        tbody.appendChild(tr);
    }

    answersEl.append(thead, tbody);
}

function exerciseTruthString(exerciseIndex) {
    return (currentExercises[exerciseIndex - 1] || "").trim();
}

function exerciseTruthCompact(exerciseIndex) {
    return exerciseTruthString(exerciseIndex).replace(/\s+/g, "");
}

function revealCorrectAnswers() {
    answersEl.querySelectorAll("[data-correct-for]").forEach((cell) => {
        const exerciseIndex = Number(cell.dataset.correctFor);
        const truth = exerciseTruthString(exerciseIndex);
        cell.textContent = truth;
        const input = answersEl.querySelector(
            `.answer-row__input[data-exercise-index="${exerciseIndex}"]`,
        );
        const answer = input ? input.value.trim().toUpperCase().replace(/\s+/g, "") : "";
        cell.dataset.correct = answer === exerciseTruthCompact(exerciseIndex) ? "true" : "false";
    });
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

function appendTruthSymbol(event) {
    const exerciseIndex = event.exercise_index;
    if (!Number.isInteger(exerciseIndex) || exerciseIndex <= 0) return;
    while (currentExercises.length < exerciseIndex) currentExercises.push("");
    const existing = currentExercises[exerciseIndex - 1] || "";
    currentExercises[exerciseIndex - 1] = existing
        ? `${existing} ${event.symbol}`
        : String(event.symbol || "");
}

// Push a Vosk final into the per-exercise capture buffer and render it
// on the Truth view next to engine symbols. Events that arrive before
// the first engine symbol fires (active index still 0) attach to the
// first exercise's bucket — Vosk can fire mid-countdown if the user
// speaks early, and dropping those entirely would hide an interesting
// timing failure.
function recordVoiceFinal(text, symbols) {
    const exerciseIdx = Math.max(1, currentExerciseIndex);
    const now = performance.now();
    const tSeconds = (performance.now() - sessionStartMs) / 1000;
    const entry = { t: round4(tSeconds), text: text, symbols: Array.from(symbols) };
    if (diagnosticTail?.exerciseIndex === exerciseIdx) {
        appendRecognitionDiagnostic(exerciseIdx, entry);
        renderVoiceEvent(entry, { late: true });
        return;
    }
    while (voiceCapture.length < exerciseIdx) voiceCapture.push([]);
    voiceCapture[exerciseIdx - 1].push(entry);
    lastVoiceFinalByExercise[exerciseIdx - 1] = now;
    markExerciseVoiceActivity(exerciseIdx);
    renderVoiceEvent(entry);
}

function round4(n) {
    return Math.round(n * 10000) / 10000;
}

function renderVoiceEvent(entry, { late = false } = {}) {
    const li = document.createElement("li");
    li.dataset.kind = late ? "voice-late" : "voice";
    li.dataset.exerciseIndex = String(Math.max(1, currentExerciseIndex));
    const time = document.createElement("span");
    time.className = "events-time";
    time.textContent = `${entry.t.toFixed(2)}s`;
    const arrow = document.createElement("span");
    arrow.className = "events-voice-text";
    const rendered = entry.symbols.length
        ? `${entry.text} → ${entry.symbols.join("")}`
        : `${entry.text} → —`;
    arrow.textContent = late ? `late: ${rendered}` : rendered;
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

function completeRecognitionExercise(exerciseIndex) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    if (pendingExerciseCompletion?.exerciseIndex === exerciseIndex) {
        clearPendingExerciseCompletion();
    }
    const input = answersEl.querySelector(
        `.answer-row__input[data-exercise-index="${exerciseIndex}"]`,
    );
    socket.send(JSON.stringify({
        action: "complete-recognition-exercise",
        exercise_index: exerciseIndex,
        answer: input ? input.value : "",
        voice_capture: voiceCapture[exerciseIndex - 1] || [],
    }));
    openDiagnosticTail(exerciseIndex);
}

function openDiagnosticTail(exerciseIndex) {
    clearDiagnosticTail();
    diagnosticTail = {
        exerciseIndex,
        timer: window.setTimeout(clearDiagnosticTail, EXERCISE_DIAGNOSTIC_TAIL_MS),
    };
}

function appendRecognitionDiagnostic(exerciseIndex, entry) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({
        action: "append-recognition-diagnostic",
        exercise_index: exerciseIndex,
        late_voice_capture: [{ ...entry, reason: "after_committed_response" }],
    }));
}

function scheduleRecognitionExerciseCompletion(exerciseIndex) {
    clearPendingExerciseCompletion();
    const now = performance.now();
    const lastVoiceAt = lastVoiceFinalByExercise[exerciseIndex - 1] || null;
    pendingExerciseCompletion = {
        exerciseIndex,
        endedAt: now,
        lastVoiceAt,
        timer: null,
    };
    schedulePendingExerciseCompletionTimer();
}

function markExerciseVoiceActivity(exerciseIndex) {
    if (pendingExerciseCompletion?.exerciseIndex !== exerciseIndex) return;
    pendingExerciseCompletion.lastVoiceAt = performance.now();
    schedulePendingExerciseCompletionTimer();
}

function schedulePendingExerciseCompletionTimer() {
    if (!pendingExerciseCompletion) return;
    if (pendingExerciseCompletion.timer) {
        window.clearTimeout(pendingExerciseCompletion.timer);
        pendingExerciseCompletion.timer = null;
    }

    const now = performance.now();
    const hardDeadline =
        pendingExerciseCompletion.endedAt + EXERCISE_COMPLETION_HARD_CAP_MS;
    // If no speech evidence is present, give the recognizer a bounded
    // initial grace period. Once any partial/final activity appears, move
    // to a shorter quiet-period rule so accurate prompt answers do not sit
    // through the full grace window before the next exercise starts.
    const voiceActivityAt = pendingExerciseCompletion.lastVoiceAt == null
        ? null
        : Math.max(pendingExerciseCompletion.lastVoiceAt, pendingExerciseCompletion.endedAt);
    const preferredDeadline = voiceActivityAt == null
        ? pendingExerciseCompletion.endedAt + EXERCISE_COMPLETION_INITIAL_GRACE_MS
        : voiceActivityAt + EXERCISE_COMPLETION_QUIET_MS;
    const deadline = Math.min(preferredDeadline, hardDeadline);
    const delay = Math.max(0, deadline - now);
    pendingExerciseCompletion.timer = window.setTimeout(() => {
        const exerciseIndex = pendingExerciseCompletion?.exerciseIndex;
        if (exerciseIndex != null) completeRecognitionExercise(exerciseIndex);
    }, delay);
}

// ─── Recognition timing review ───────────────────────────────────────────────

function clearRecognitionTimingReview() {
    timingTabsEl?.replaceChildren();
    timingEl?.replaceChildren();
    selectedTimingExerciseIndex = 1;
}

function timingWindowMs() {
    const firstSymbol = symbolEventsByExercise
        .flat()
        .find((event) => Number.isFinite(event.t_on) && Number.isFinite(event.t_off));
    const symbolDurationMs = firstSymbol
        ? Math.max(1, (firstSymbol.t_off - firstSymbol.t_on) * 1000)
        : 0;
    let observedGapMs = 0;
    for (const events of symbolEventsByExercise) {
        for (let i = 0; i < events.length - 1; i++) {
            const current = events[i];
            const next = events[i + 1];
            if (Number.isFinite(current.t_off) && Number.isFinite(next.t_on)) {
                observedGapMs = Math.max(observedGapMs, (next.t_on - current.t_off) * 1000);
            }
        }
    }
    return Math.max(1500, Math.round(symbolDurationMs + observedGapMs));
}

function pairVoiceEventsWithTargets(exerciseIndex) {
    const targets = symbolEventsByExercise[exerciseIndex - 1] || [];
    const voiceEvents = voiceCapture[exerciseIndex - 1] || [];
    const spoken = [];
    voiceEvents.forEach((entry) => {
        (entry.symbols || []).forEach((symbol) => {
            spoken.push({ symbol, t: Number(entry.t) });
        });
    });
    return targets.map((target, idx) => {
        const heard = spoken[idx];
        if (!heard || !Number.isFinite(heard.t) || !Number.isFinite(target.t_on)) return null;
        return {
            symbol: heard.symbol,
            latencyMs: Math.max(0, Math.round((heard.t - target.t_on) * 1000)),
        };
    });
}

function buildTimingExerciseBlock(exerciseIndex) {
    const exercise = exerciseTruthString(exerciseIndex);
    const targets = symbolEventsByExercise[exerciseIndex - 1] || [];
    const responses = pairVoiceEventsWithTargets(exerciseIndex);
    const windowMs = timingWindowMs();

    const block = document.createElement("section");
    block.className = "key-rhythm-baseline__exercise recognition-timing__exercise";
    block.setAttribute("aria-label", `Exercise ${exerciseIndex} recognition timing`);

    const label = document.createElement("p");
    label.className = "key-rhythm-baseline__exercise-label";
    label.textContent = `Exercise ${exerciseIndex} / ${exercise || "-"}`;
    block.appendChild(label);

    const cols = document.createElement("div");
    cols.className = "key-rhythm-baseline__cols";
    targets.forEach((target, idx) => {
        const col = document.createElement("div");
        col.className = "key-rhythm-baseline__col key-rhythm-baseline__col--char";

        const symbol = document.createElement("span");
        symbol.className = "key-rhythm-baseline__symbol";
        symbol.textContent = target.symbol;

        const zones = document.createElement("div");
        zones.className = "key-rhythm-baseline__zones";
        zones.setAttribute("aria-hidden", "true");
        ["green", "amber", "red"].forEach((zone) => {
            const cell = document.createElement("span");
            cell.className = `key-rhythm-baseline__zone key-rhythm-baseline__zone--${zone}`;
            zones.appendChild(cell);
        });

        const attempt = document.createElement("div");
        attempt.className = "key-rhythm-baseline__attempt";
        const response = responses[idx];
        if (response) {
            const marker = document.createElement("div");
            marker.className = "key-rhythm-baseline__attempt-marker";
            marker.style.setProperty(
                "--attempt-x",
                String(Math.min(1, response.latencyMs / windowMs)),
            );
            marker.title = `${response.symbol} at ${(response.latencyMs / 1000).toFixed(2)}s`;
            const arrow = document.createElement("span");
            arrow.className = "key-rhythm-baseline__attempt-arrow";
            arrow.setAttribute("aria-hidden", "true");
            arrow.textContent = "↑";
            const heard = document.createElement("span");
            heard.className = "key-rhythm-baseline__attempt-symbol";
            heard.textContent = response.symbol;
            marker.append(arrow, heard);
            attempt.appendChild(marker);
        }
        col.append(symbol, zones, attempt);
        cols.appendChild(col);
    });
    block.appendChild(cols);
    return block;
}

function renderRecognitionTimingReview() {
    if (!timingTabsEl || !timingEl) return;
    timingTabsEl.replaceChildren();
    timingEl.replaceChildren();
    const indices = currentExercises
        .map((exercise, idx) => (exercise && exercise.trim() ? idx + 1 : -1))
        .filter((idx) => idx > 0);
    if (!indices.length) return;
    if (!indices.includes(selectedTimingExerciseIndex)) {
        selectedTimingExerciseIndex = indices[0];
    }

    indices.forEach((exerciseIndex, tabIdx) => {
        const tab = document.createElement("button");
        tab.type = "button";
        tab.className = "key-rhythm-review__tab";
        tab.role = "tab";
        tab.textContent = `${tabIdx + 1} / ${exerciseTruthCompact(exerciseIndex)}`;
        const selected = exerciseIndex === selectedTimingExerciseIndex;
        tab.setAttribute("aria-selected", String(selected));
        if (selected) tab.dataset.selected = "true";
        tab.addEventListener("click", () => {
            selectedTimingExerciseIndex = exerciseIndex;
            renderRecognitionTimingReview();
        });
        timingTabsEl.appendChild(tab);
    });

    timingEl.appendChild(buildTimingExerciseBlock(selectedTimingExerciseIndex));
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

async function beginCountdownThenStart() {
    try {
        await ensureVoiceCaptureReady();
    } catch (err) {
        const li = document.createElement("li");
        li.textContent = `! voice: ${err.message || err}`;
        li.dataset.kind = "error";
        eventsEl.appendChild(li);
        setStartButtonMode("idle");
        return;
    }

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

function hasUnsavedRecognitionAnswers() {
    return currentExercises.length > 0
        && saveBtn.dataset.state === "ready"
        && !saveBtn.disabled;
}

function sendRecognitionAnswers() {
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving";
    socket.send(JSON.stringify({
        action: "save-recognition-answers",
        answers: collectAnswers(),
        voice_capture: voiceCapture,
    }));
    return true;
}

function saveRecognitionAnswers() {
    if (!sendRecognitionAnswers()) return Promise.resolve(false);
    return new Promise((resolve) => {
        pendingSaveResolve = resolve;
    });
}

async function autosaveBeforeStart() {
    if (!hasUnsavedRecognitionAnswers()) return true;
    return saveRecognitionAnswers();
}

startBtn.addEventListener("click", async () => {
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
    startBtn.disabled = true;
    const saved = await autosaveBeforeStart();
    if (!saved) {
        setStartButtonMode("idle");
        return;
    }
    await beginCountdownThenStart();
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

// ─── Symbol preview (Left Alt + key) ──────────────────────────────────────────
// Plays a claimed symbol's bare Morse three times through the engine so the
// learner can refresh their ear between sessions. ``event.code`` is used
// because Option+letter on macOS substitutes the character in ``event.key``;
// LeftAlt is tracked separately because ``event.altKey`` does not
// distinguish left from right.

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

let leftAltDown = false;

window.addEventListener("keydown", (event) => {
    if (event.code === "AltLeft") {
        leftAltDown = true;
        return;
    }
    if (!leftAltDown || !event.altKey) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    // Preview audio would collide with in-flight session playback.
    if (sessionActive) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
    }
    const symbol = symbolForPreviewCode(event.code, event.shiftKey);
    if (!symbol) return;
    // Only claimed symbols are previewable. The fixed DE listening
    // anchor (spec §2.5) is deliberately ear-only and not available
    // for active review here.
    if (!claimedState.symbols.includes(symbol)) return;
    event.preventDefault();
    if (event.repeat) return;
    socket.send(JSON.stringify({ action: "play-morse-repeat", symbol }));
});

window.addEventListener("keyup", (event) => {
    if (event.code === "AltLeft") {
        leftAltDown = false;
    }
});

window.addEventListener("blur", () => {
    leftAltDown = false;
});

// ─── Event handling ──────────────────────────────────────────────────────────

function appendEvent(event) {
    if (event.type === "claimed-symbols") {
        claimedState = event;
        currentSetSession = Number.isInteger(event.recognition_set_session)
            ? event.recognition_set_session
            : currentSetSession;
        currentRecognitionGear = Number.isInteger(event.recognition_gear)
            ? event.recognition_gear
            : currentRecognitionGear;
        currentRecognitionKind = typeof event.recognition_kind === "string"
            ? event.recognition_kind
            : currentRecognitionKind;
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
        const exerciseCount = Number.isInteger(event.exercise_count) ? event.exercise_count : 0;
        currentExercises = Array.from({ length: exerciseCount }, () => "");
        currentExerciseIndex = 0;
        currentSetSession = event.set_session || 0;
        currentRecognitionGear = Number.isInteger(event.gear) ? event.gear : null;
        currentRecognitionKind = typeof event.recognition_kind === "string"
            ? event.recognition_kind
            : "";
        sessionActive = true;
        sessionStartMs = performance.now();
        voiceCapture = currentExercises.map(() => []);
        symbolEventsByExercise = currentExercises.map(() => []);
        lastVoiceFinalByExercise = currentExercises.map(() => null);
        clearRecognitionTimingReview();
        clearPendingExerciseCompletion();
        clearDiagnosticTail();
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
        saveBtn.dataset.state = "idle";
        saveBtn.textContent = "Save";
        primedTextEl.textContent = `Exercise — of ${currentExercises.length}`;
        primedSetEl.textContent = recognitionSetNotice();
        // Voice capture is normally pre-warmed before the start request
        // so Exercise 1 is captured. This fallback keeps a direct server
        // start or reconnect from leaving the page silent.
        ensureVoiceCaptureReady().catch((err) => {
            const li = document.createElement("li");
            li.textContent = `! voice: ${err.message || err}`;
            li.dataset.kind = "error";
            eventsEl.appendChild(li);
        });
        return;
    }

    if (event.type === "recognition-exercise-start") {
        clearDiagnosticTail();
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
        header.textContent = `Exercise ${event.exercise_index}`;
        eventsEl.appendChild(header);
        primedTextEl.textContent =
            `Exercise ${currentExerciseIndex} of ${currentExercises.length}`;
        return;
    }

    if (event.type === "symbol") {
        appendTruthSymbol(event);
        if (Number.isInteger(event.exercise_index) && event.exercise_index > 0) {
            while (symbolEventsByExercise.length < event.exercise_index) {
                symbolEventsByExercise.push([]);
            }
            symbolEventsByExercise[event.exercise_index - 1].push({ ...event });
        }
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

    if (event.type === "recognition-exercise-end") {
        scheduleRecognitionExerciseCompletion(event.exercise_index);
        return;
    }

    if (event.type === "session-end") {
        sessionActive = false;
        clearPendingExerciseCompletion();
        clearDiagnosticTail();
        stopVoiceCapture();
        unlockAnswerInputs();
        revealCorrectAnswers();
        renderRecognitionTimingReview();
        saveBtn.disabled = true;
        saveBtn.dataset.state = "saved";
        saveBtn.textContent = "Saved";
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
        if (pendingSaveResolve) {
            pendingSaveResolve(true);
            pendingSaveResolve = null;
        }
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
        clearPendingExerciseCompletion();
        clearDiagnosticTail();
        stopVoiceCapture();
        setTimelineLocked(false);
        if (pendingSaveResolve) {
            pendingSaveResolve(false);
            pendingSaveResolve = null;
        }
        if (saveBtn.textContent === "Saving") {
            saveBtn.disabled = false;
            saveBtn.textContent = "Save";
        }
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
    sendRecognitionAnswers();
});

// Allow re-saving after edits.
answersEl.addEventListener("input", (event) => {
    if (!(event.target instanceof HTMLInputElement)) return;
    revealCorrectAnswers();
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
