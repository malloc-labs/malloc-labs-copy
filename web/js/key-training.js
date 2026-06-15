// Copy — Key Training page entry.
//
// Training is intentionally user-directed: the Sequence row manages
// claimed symbols, while the custom input selects the symbol queue used
// by the paddle choreography visualizer. Live attempt capture and
// Settings records will layer on this target model later.

import {
    connectKoch,
    installClaimHandlers,
    renderSequence,
    setStatus,
    setSequenceTokenPlaying,
} from "./koch-core.js";
import {
    renderKeyPageActionsToggleLabel,
    toggleKeyPageActions,
} from "./key-timing/collapsibles.js";
import {
    diagnosticText,
    installDiagnosticsAccessors,
    recordDiagnostic,
} from "./key-timing/diagnostics.js";
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
import {
    enableSidetone,
    isSoundEnabled,
    sidetone,
    toggleSidetone,
    updateAudioDiagnostic,
} from "./key-timing/sidetone.js";
import { keyInputToggleEl, copyDiagnosticsEl } from "./key-timing/dom.js";
import { initTrinkeySyncIndicator } from "./key-timing/trinkey-sync-indicator.js";
import { PATTERNS, spokenMorsePattern } from "./morse-display.js";
import { hideSymbolPreview, showSymbolPreview, symbolForPreviewCode } from "./symbol-preview.js";

const STORAGE_KEY = "copy-653.key-training-input";
const APPLY_DEBOUNCE_MS = 150;
const DEFAULT_QUEUE = ["K"];

const sequenceRow = document.getElementById("sequence-row");
const inputEl = document.getElementById("training-custom-input");
const toggleEl = document.getElementById("training-custom-toggle");
const arrowEl = document.getElementById("training-custom-arrow");
const bodyEl = document.getElementById("training-custom-body");
const labelEl = document.getElementById("training-custom-label");
const titleEl = document.getElementById("training-focus-title");
const metaEl = document.getElementById("training-focus-meta");
const queueEl = document.getElementById("training-symbol-queue");
const playSequenceEl = document.getElementById("training-play-sequence");
const restartEl = document.getElementById("training-restart");
const lastKeyedEl = document.getElementById("training-last-keyed-symbol");
const chartEl = document.getElementById("training-paddle-chart");
const eventsEl = document.getElementById("training-chart-events");
const axisEl = document.getElementById("training-chart-axis");
const noteEl = document.getElementById("training-focus-note");

let socket = null;
let claimedSymbolSet = new Set();
let leftAltDown = false;
let keyerMode = "iambic_a";
let characterWpm = 20;
let symbolQueue = [...DEFAULT_QUEUE];
let activeIndex = 0;
let completedThroughIndex = -1;
let applyTimer = null;
let lastKeyedSymbol = "";
let playbackIndex = null;
let playbackRunId = 0;
let playbackTimeout = null;
let playbackResolve = null;
let playbackRestoreIndex = null;
let pendingObservedElements = [];
let observedAttemptsByIndex = new Map();
let leftAltUsedWithPreview = false;

const KEYER_MODE_DISPLAY = {
    iambic_a: "Iambic A",
    ultimatic: "Ultimatic",
    iambic_b: "Iambic B",
};

function renderKeyerModeBadge(mode) {
    const el = document.getElementById("key-mode-badge");
    if (!el) return;
    const label = KEYER_MODE_DISPLAY[mode] || (mode ? mode.replace(/_/g, " ") : "—");
    el.textContent = label;
    el.dataset.keyerMode = mode || "";
}

function modeDisplay(mode) {
    return KEYER_MODE_DISPLAY[mode] || (mode ? mode.replace(/_/g, " ") : "—");
}

function ditMs() {
    return 1200 / Math.max(1, characterWpm);
}

function appendEvent(event) {
    if (event.type === "claimed-symbols") {
        claimedSymbolSet = renderSequence(sequenceRow, event);
        return;
    }
    if (event.type === "audio-settings") {
        keyerMode = event.keyer_mode || keyerMode;
        const nextWpm = Number(event.character_speed_wpm);
        if (Number.isFinite(nextWpm) && nextWpm > 0) characterWpm = nextWpm;
        renderKeyerModeBadge(keyerMode);
        renderTrainingFocus();
        return;
    }
    if (event.type === "morse-repeat-start") {
        setSequenceTokenPlaying(sequenceRow, event.symbol, true);
        return;
    }
    if (event.type === "morse-repeat-end") {
        setSequenceTokenPlaying(sequenceRow, event.symbol, false);
        hideSymbolPreview();
        return;
    }
    if (event.type === "key-input-start") {
        renderKeyInputStart(event);
        return;
    }
    if (event.type === "key-event") {
        noteObservedKeyEvent(event);
        renderKeyEvent(event);
        return;
    }
    if (event.type === "key-input-reset") {
        pendingObservedElements = [];
        observedAttemptsByIndex = new Map();
        renderKeyInputReset(event);
        renderTrainingFocus();
        return;
    }
    if (event.type === "sent-symbol") {
        appendDiagnosticRow(event);
        captureObservedAttempt(event);
        noteTrainingAttempt(event.symbol);
        return;
    }
    if (event.type === "error") {
        renderError(event);
    }
}

function initialiseTrainingInput() {
    if (!inputEl) return;

    const stored = loadStored();
    if (stored !== null) inputEl.value = stored;
    applyInputImmediate(inputEl.value);
    renderToggleLabel();

    inputEl.addEventListener("input", () => {
        if (applyTimer !== null) clearTimeout(applyTimer);
        applyTimer = window.setTimeout(() => {
            applyTimer = null;
            saveStored(inputEl.value);
            applyInputImmediate(inputEl.value);
        }, APPLY_DEBOUNCE_MS);
    });

    if (toggleEl) {
        toggleEl.addEventListener("click", () => {
            const expanded = toggleEl.getAttribute("aria-expanded") === "true";
            setSectionExpanded(!expanded);
        });
    }

    window.addEventListener("keydown", (event) => {
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        const target = event.target;
        if (target instanceof HTMLElement) {
            const tag = target.tagName;
            if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
        }
        if (event.key.toLowerCase() === "i") {
            event.preventDefault();
            const expanded = toggleEl?.getAttribute("aria-expanded") === "true";
            setSectionExpanded(!expanded);
        }
    });
}

function applyInputImmediate(raw) {
    if (playSequenceEl?.dataset.playing === "true") stopSequencePlayback();
    const nextQueue = normaliseSymbols(raw);
    symbolQueue = nextQueue.length ? nextQueue : [...DEFAULT_QUEUE];
    activeIndex = firstSymbolIndex(symbolQueue);
    completedThroughIndex = -1;
    lastKeyedSymbol = "";
    pendingObservedElements = [];
    observedAttemptsByIndex = new Map();
    renderTrainingFocus();
    renderLastKeyed();
}

function normaliseSymbols(raw) {
    const tokens = [];
    let pendingSpace = false;
    [...String(raw || "").toUpperCase()].forEach((char) => {
        if (/\s/.test(char)) {
            pendingSpace = tokens.length > 0;
            return;
        }
        if (!PATTERNS[char]) return;
        if (pendingSpace) {
            tokens.push(" ");
            pendingSpace = false;
        }
        tokens.push(char);
    });
    return tokens;
}

function renderTrainingFocus() {
    const focusIndex = playbackIndex ?? activeIndex;
    const displayIndex = symbolQueue[focusIndex] === " "
        ? nextSymbolIndex(symbolQueue, focusIndex)
        : focusIndex;
    const resolvedIndex = displayIndex !== -1 && PATTERNS[symbolQueue[displayIndex]]
        ? displayIndex
        : previousSymbolIndex(symbolQueue, focusIndex - 1);
    const symbol = symbolQueue[resolvedIndex] || DEFAULT_QUEUE[0];
    const pattern = PATTERNS[symbol];
    if (!pattern) return;

    if (titleEl) {
        const spoken = spokenMorsePattern(pattern).toLowerCase();
        titleEl.textContent = `${symbol}: ${spoken}`;
        titleEl.dataset.patternLength = pattern.length >= 6 ? "long" : pattern.length >= 5 ? "medium" : "short";
    }
    if (metaEl) {
        metaEl.textContent = `${modeDisplay(keyerMode)} · ${Math.round(characterWpm)} WPM`;
    }
    if (noteEl) {
        noteEl.textContent = noteForMode(keyerMode);
    }
    renderQueue();
    renderPaddleChart(symbol, pattern, resolvedIndex);
    renderRestartState();
}

function renderQueue() {
    if (!queueEl) return;
    queueEl.replaceChildren();
    const focusIndex = playbackIndex ?? activeIndex;
    symbolQueue.forEach((symbol, idx) => {
        if (symbol === " ") {
            const space = document.createElement("span");
            space.className = "key-training-queue__space";
            space.dataset.completed = idx <= completedThroughIndex ? "true" : "false";
            space.setAttribute("aria-label", "word space");
            queueEl.appendChild(space);
            return;
        }
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "key-training-queue__item";
        btn.textContent = symbol;
        btn.dataset.active = idx === focusIndex ? "true" : "false";
        btn.dataset.completed = idx <= completedThroughIndex ? "true" : "false";
        btn.setAttribute("aria-pressed", String(idx === focusIndex));
        btn.title = idx === focusIndex ? `Current target: ${symbol}` : `Train ${symbol}`;
        btn.addEventListener("click", () => {
            stopSequencePlayback();
            activeIndex = idx;
            renderTrainingFocus();
        });
        queueEl.appendChild(btn);
    });
}

function restartTrainingRun() {
    stopSequencePlayback();
    activeIndex = firstSymbolIndex(symbolQueue);
    completedThroughIndex = -1;
    lastKeyedSymbol = "";
    pendingObservedElements = [];
    observedAttemptsByIndex = new Map();
    renderTrainingFocus();
    renderLastKeyed();
}

function navigateTrainingReview(direction) {
    stopSequencePlayback();
    const currentIndex = currentReviewIndex();
    const nextIndex = direction < 0
        ? previousSymbolIndex(symbolQueue, currentIndex - 1)
        : nextSymbolIndex(symbolQueue, currentIndex + 1);
    if (nextIndex === -1 || nextIndex === currentIndex) return;
    activeIndex = nextIndex;
    renderTrainingFocus();
}

function currentReviewIndex() {
    if (symbolQueue[activeIndex] && symbolQueue[activeIndex] !== " ") return activeIndex;
    return previousSymbolIndex(symbolQueue, activeIndex - 1);
}

function noteTrainingAttempt(symbol) {
    if (!symbol) return;
    lastKeyedSymbol = String(symbol).toUpperCase();
    renderLastKeyed();

    const target = symbolQueue[activeIndex];
    if (target !== lastKeyedSymbol) {
        renderTrainingFocus();
        return;
    }

    const nextIndex = nextSymbolIndex(symbolQueue, activeIndex + 1);
    if (nextIndex === -1) {
        completedThroughIndex = symbolQueue.length - 1;
        activeIndex = symbolQueue.length;
    } else {
        completedThroughIndex = nextIndex - 1;
        activeIndex = nextIndex;
    }
    renderTrainingFocus();
}

function renderLastKeyed() {
    if (!lastKeyedEl) return;
    lastKeyedEl.textContent = lastKeyedSymbol || "—";
    lastKeyedEl.dataset.empty = lastKeyedSymbol ? "false" : "true";
}

function renderRestartState() {
    if (!restartEl) return;
    restartEl.dataset.completed = trainingSequenceCompleted() ? "true" : "false";
}

function trainingSequenceCompleted() {
    return completedThroughIndex >= symbolQueue.length - 1;
}

function installTrainingNavigationControls() {
    if (restartEl) {
        restartEl.addEventListener("click", restartTrainingRun);
    }
    window.addEventListener("keydown", (event) => {
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        const target = event.target;
        if (target instanceof HTMLElement) {
            const tag = target.tagName;
            if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
        }
        const key = event.key.toLowerCase();
        if (key === "r") {
            event.preventDefault();
            restartTrainingRun();
        } else if (key === "h") {
            event.preventDefault();
            navigateTrainingReview(-1);
        } else if (key === "l") {
            event.preventDefault();
            navigateTrainingReview(1);
        }
    });
}

function firstSymbolIndex(tokens) {
    const idx = nextSymbolIndex(tokens, 0);
    return idx === -1 ? 0 : idx;
}

function nextSymbolIndex(tokens, start) {
    for (let idx = start; idx < tokens.length; idx += 1) {
        if (tokens[idx] !== " ") return idx;
    }
    return -1;
}

function previousSymbolIndex(tokens, start) {
    for (let idx = Math.min(start, tokens.length - 1); idx >= 0; idx -= 1) {
        if (tokens[idx] !== " ") return idx;
    }
    return 0;
}

function renderPaddleChart(symbol, pattern, tokenIndex) {
    if (!chartEl || !eventsEl || !axisEl) return;
    chartEl.querySelectorAll(".key-training-chart__bar").forEach((el) => el.remove());
    eventsEl.replaceChildren();
    axisEl.replaceChildren();

    const plan = buildTrainingPlan(symbol, pattern, keyerMode);
    const totalUnits = plan.totalUnits;
    const unitMs = ditMs();

    plan.laneBars.forEach((bar) => {
        const rail = chartEl.querySelector(`[data-lane="${bar.lane}"]`);
        if (!rail) return;
        const el = document.createElement("div");
        el.className = `key-training-chart__bar key-training-chart__bar--${bar.lane}`;
        el.style.setProperty("--bar-bottom", `${(bar.start / totalUnits) * 100}%`);
        el.style.setProperty("--bar-height", `${((bar.end - bar.start) / totalUnits) * 100}%`);
        el.dataset.action = bar.action;
        const label = document.createElement("span");
        label.textContent = bar.label;
        el.appendChild(label);
        rail.appendChild(el);
    });

    plan.elements.forEach((element) => {
        const el = document.createElement("div");
        el.className = `key-training-chart__event key-training-chart__event--${element.kind}`;
        el.style.setProperty("--event-bottom", `${((element.start + element.duration / 2) / totalUnits) * 100}%`);
        el.dataset.eventIndex = String(element.index);
        el.textContent = `${element.kind.toUpperCase()} ${Math.round(element.duration * unitMs)} ms`;
        eventsEl.appendChild(el);
    });
    renderObservedElements(tokenIndex, plan, unitMs);

    [0, 0.25, 0.5, 0.75, 1].forEach((ratio) => {
        const tick = document.createElement("span");
        tick.className = "key-training-chart__tick";
        tick.style.setProperty("--tick-bottom", `${ratio * 100}%`);
        tick.textContent = `${Math.round(ratio * totalUnits * unitMs)} ms`;
        axisEl.appendChild(tick);
    });
}

function noteObservedKeyEvent(event) {
    if (event.pressed) {
        if (playSequenceEl?.dataset.playing === "true") stopSequencePlayback();
        const targetIndex = observedTargetIndex();
        if (observedAttemptsByIndex.has(targetIndex)) {
            observedAttemptsByIndex.delete(targetIndex);
            renderTrainingFocus();
        }
        return;
    }
    const durationMs = Number(event.duration_ms);
    const endedAt = Number(event.timestamp);
    if (!event.kind || !Number.isFinite(durationMs) || !Number.isFinite(endedAt)) return;
    pendingObservedElements.push({
        kind: event.kind,
        startedAt: endedAt - durationMs / 1000,
        endedAt,
        durationMs,
    });
    if (pendingObservedElements.length > 16) {
        pendingObservedElements = pendingObservedElements.slice(-16);
    }
}

function captureObservedAttempt(event) {
    const startedAt = Number(event.started_at);
    const endedAt = Number(event.ended_at);
    if (!Number.isFinite(startedAt) || !Number.isFinite(endedAt)) return;
    const targetIndex = observedTargetIndex();

    const elements = pendingObservedElements.filter((element) => (
        element.endedAt >= startedAt && element.endedAt <= endedAt
    ));
    pendingObservedElements = pendingObservedElements.filter((element) => element.endedAt > endedAt);

    if (elements.length) {
        observedAttemptsByIndex.set(targetIndex, {
            symbol: String(event.symbol || "").toUpperCase(),
            startedAt,
            endedAt,
            elements,
        });
    } else {
        observedAttemptsByIndex.delete(targetIndex);
    }
}

function observedTargetIndex() {
    if (symbolQueue[activeIndex] && symbolQueue[activeIndex] !== " ") return activeIndex;
    const previous = previousSymbolIndex(symbolQueue, activeIndex - 1);
    return symbolQueue[previous] && symbolQueue[previous] !== " " ? previous : firstSymbolIndex(symbolQueue);
}

function renderObservedElements(tokenIndex, plan, unitMs) {
    if (!eventsEl) return;
    const attempt = observedAttemptsByIndex.get(tokenIndex);
    if (!attempt) return;

    const unitSeconds = unitMs / 1000;
    attempt.elements.forEach((element, idx) => {
        const centerUnits = (
            ((element.startedAt + element.endedAt) / 2) - attempt.startedAt
        ) / unitSeconds;
        const expected = expectedObservedElement(plan.elements, element, idx);
        const expectedCenter = expected ? expected.start + expected.duration / 2 : centerUnits;
        const deltaUnits = centerUnits - expectedCenter;
        const clampedUnits = Math.min(Math.max(centerUnits, 0), plan.totalUnits);
        const marker = document.createElement("span");
        marker.className = `key-training-chart__observed key-training-chart__observed--${element.kind}`;
        marker.style.setProperty("--observed-bottom", `${(clampedUnits / plan.totalUnits) * 100}%`);
        marker.dataset.fit = Math.abs(deltaUnits) <= 0.35 ? "close" : "wide";
        marker.title = observedMarkerTitle(element, deltaUnits, unitMs);
        eventsEl.appendChild(marker);
    });
}

function expectedObservedElement(elements, observed, observedIndex) {
    const sameKind = elements.filter((element) => element.kind === observed.kind)[observedIndex];
    if (sameKind) return sameKind;
    return elements[observedIndex] || null;
}

function observedMarkerTitle(element, deltaUnits, unitMs) {
    const deltaMs = Math.round(deltaUnits * unitMs);
    const direction = deltaMs === 0
        ? "on time"
        : deltaMs > 0
            ? `${deltaMs} ms late`
            : `${Math.abs(deltaMs)} ms early`;
    return `observed ${element.kind} ${direction} / ${Math.round(element.durationMs)} ms`;
}

function buildTrainingPlan(symbol, pattern, mode) {
    const elements = [];
    let cursor = 0;
    [...pattern].forEach((mark, idx) => {
        const kind = mark === "-" ? "dah" : "dit";
        const duration = kind === "dah" ? 3 : 1;
        elements.push({ index: idx, kind, start: cursor, end: cursor + duration, duration });
        cursor += duration;
        if (idx < pattern.length - 1) cursor += 1;
    });

    return {
        elements,
        laneBars: buildLaneBars(symbol, elements, mode),
        totalUnits: Math.max(cursor, 1),
    };
}

function buildLaneBars(symbol, elements, mode) {
    const bars = mode === "iambic_a"
        ? buildIambicAModeBars(elements)
        : mode === "iambic_b"
            ? buildGenericBars(elements)
            : buildEfficientBars(symbol, elements);
    return bars.map((bar) => ({
        ...bar,
        label: bar.label || (bar.action === "squeeze" ? "SQUEEZED" : "HELD"),
    }));
}

function buildIambicAModeBars(elements) {
    if (!elements.length) return [];

    return ["dit", "dah"].flatMap((kind) => {
        const laneElements = elements.filter((element) => element.kind === kind);
        if (!laneElements.length) return [];
        const first = laneElements[0];
        const last = laneElements[laneElements.length - 1];
        const startsSequence = first.index === 0;
        return {
            lane: kind,
            start: first.start,
            end: last.end,
            action: startsSequence ? "press" : "squeeze",
            label: startsSequence ? "HELD" : "SQUEEZED",
        };
    });
}

function buildEfficientBars(symbol, elements) {
    if (symbol === "K" && elements.length === 3) {
        return [
            { lane: "dah", start: elements[0].start, end: elements[2].end, action: "hold", label: "HELD" },
            { lane: "dit", start: elements[1].start, end: elements[1].end, action: "squeeze", label: "SQUEEZED" },
        ];
    }
    if (symbol === "R" && elements.length === 3) {
        return [
            { lane: "dit", start: elements[0].start, end: elements[0].end, action: "press", label: "PRESS" },
            { lane: "dah", start: elements[1].start, end: elements[1].end, action: "squeeze", label: "SQUEEZED" },
            { lane: "dit", start: elements[2].start, end: elements[2].end, action: "squeeze", label: "SQUEEZED" },
        ];
    }
    if (symbol === "U" && elements.length === 3) {
        return [
            { lane: "dit", start: elements[0].start, end: elements[1].end, action: "hold", label: "HELD" },
            { lane: "dah", start: elements[2].start, end: elements[2].end, action: "squeeze", label: "SQUEEZED" },
        ];
    }
    return buildGenericBars(elements);
}

function buildGenericBars(elements) {
    const bars = [];
    let current = null;
    elements.forEach((element) => {
        if (current && current.lane === element.kind && current.end + 1 === element.start) {
            current.end = element.end;
            return;
        }
        current = {
            lane: element.kind,
            start: element.start,
            end: element.end,
            action: bars.length === 0 ? "press" : "squeeze",
        };
        bars.push(current);
    });
    return bars;
}

function noteForMode(mode) {
    if (mode === "ultimatic") {
        return "Ultimatic visual: last paddle pressed wins. Canonical form is a mode-efficiency hint, not a requirement.";
    }
    if (mode === "iambic_b") {
        return "Iambic B visual: queued extra elements are shown explicitly when that model is added.";
    }
    return "Iambic A visual: release timing controls whether the keyer stops or continues. Canonical form is advisory.";
}

function setSectionExpanded(expanded) {
    if (!toggleEl || !arrowEl || !bodyEl) return;
    toggleEl.setAttribute("aria-expanded", String(expanded));
    arrowEl.textContent = expanded ? "▼" : "▶";
    bodyEl.hidden = !expanded;
    if (expanded) inputEl?.focus();
}

function renderToggleLabel() {
    if (!labelEl || !toggleEl) return;
    const u = document.createElement("u");
    u.textContent = "i";
    labelEl.replaceChildren(u, document.createTextNode("nput"));
    toggleEl.title = "Show/hide custom input (I)";
    toggleEl.setAttribute("aria-keyshortcuts", "I");
}

function loadStored() {
    try {
        return window.localStorage.getItem(STORAGE_KEY);
    } catch (_err) {
        return null;
    }
}

function saveStored(value) {
    try {
        window.localStorage.setItem(STORAGE_KEY, value || "");
    } catch (_err) {
        // Private browsing or quota failures should not break Training.
    }
}

function installPlaybackControls() {
    if (!playSequenceEl) return;
    playSequenceEl.addEventListener("click", () => {
        if (playSequenceEl.dataset.playing === "true") {
            stopSequencePlayback();
        } else {
            playTrainingSequence();
        }
    });
}

async function playTrainingSequence() {
    stopSequencePlayback({ restore: false });
    const runId = playbackRunId + 1;
    playbackRunId = runId;
    playbackRestoreIndex = activeIndex;
    playSequenceEl.dataset.playing = "true";
    playSequenceEl.textContent = "Stop";
    await enableSidetone();

    try {
        let idx = firstSymbolIndex(symbolQueue);
        while (idx !== -1 && runId === playbackRunId) {
            const symbol = symbolQueue[idx];
            const pattern = PATTERNS[symbol];
            if (pattern) {
                playbackIndex = idx;
                renderTrainingFocus();
                await playSymbolPattern(pattern, runId);
            }
            idx = nextSymbolIndex(symbolQueue, idx + 1);
            if (idx !== -1 && runId === playbackRunId) {
                await sleepUnits(hasWordSpaceBefore(idx) ? 7 : 3, runId);
            }
        }
    } finally {
        if (runId === playbackRunId) {
            stopSequencePlayback();
        }
    }
}

async function playSymbolPattern(pattern, runId) {
    const marks = [...pattern];
    for (let idx = 0; idx < marks.length; idx += 1) {
        if (runId !== playbackRunId) return;
        const mark = marks[idx];
        const durationUnits = mark === "-" ? 3 : 1;
        setPlayingTrainingEvent(idx, true);
        sidetone.keyDown(`training-playback-${runId}`);
        await sleepUnits(durationUnits, runId);
        sidetone.keyUp(`training-playback-${runId}`);
        setPlayingTrainingEvent(idx, false);
        if (idx < marks.length - 1) {
            await sleepUnits(1, runId);
        }
    }
}

function hasWordSpaceBefore(index) {
    for (let idx = index - 1; idx >= 0; idx -= 1) {
        if (symbolQueue[idx] === " ") return true;
        return false;
    }
    return false;
}

function setPlayingTrainingEvent(index, playing) {
    if (!eventsEl) return;
    eventsEl.querySelectorAll("[data-playing]").forEach((el) => {
        delete el.dataset.playing;
    });
    if (!playing) return;
    const el = eventsEl.querySelector(`[data-event-index="${index}"]`);
    if (el) el.dataset.playing = "true";
}

function sleepUnits(units, runId) {
    return new Promise((resolve) => {
        playbackResolve = resolve;
        playbackTimeout = window.setTimeout(() => {
            if (runId === playbackRunId) playbackTimeout = null;
            if (runId === playbackRunId) playbackResolve = null;
            resolve();
        }, Math.max(1, units * ditMs()));
    });
}

function stopSequencePlayback(options = {}) {
    const { restore = true } = options;
    playbackRunId += 1;
    if (playbackTimeout !== null) {
        window.clearTimeout(playbackTimeout);
        playbackTimeout = null;
    }
    if (playbackResolve) {
        playbackResolve();
        playbackResolve = null;
    }
    sidetone.keyUp(`training-playback-${playbackRunId - 1}`);
    sidetone.mute();
    setPlayingTrainingEvent(0, false);
    if (restore && playbackRestoreIndex !== null) activeIndex = playbackRestoreIndex;
    playbackRestoreIndex = null;
    playbackIndex = null;
    if (playSequenceEl) {
        delete playSequenceEl.dataset.playing;
        playSequenceEl.textContent = "Play sequence";
    }
    renderTrainingFocus();
}

function installKeyControls() {
    installMidiInputAccessors({ setStatus });
    installDiagnosticsAccessors({
        keyConfig: getKeyConfig,
        midiInputArmed: getMidiInputArmed,
    });

    if (keyInputToggleEl) {
        keyInputToggleEl.addEventListener("click", () => {
            setMidiInputArmed(!getMidiInputArmed(), "manual toggle");
        });
    }
    if (copyDiagnosticsEl) {
        copyDiagnosticsEl.addEventListener("click", copyDiagnostics);
    }

    document.addEventListener("visibilitychange", () => {
        recordDiagnostic("page-lifecycle", {
            event: "visibilitychange",
            visibility: document.visibilityState,
        });
        if (document.visibilityState === "hidden") {
            stopSequencePlayback();
            setMidiInputArmed(false, "page hidden");
        } else if (document.visibilityState === "visible" && !getMidiInputArmed()) {
            setMidiInputArmed(true, "page visible");
        }
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
        } else if (key === "t") {
            event.preventDefault();
            toggleKeyPageActions();
        }
    });

    renderKeyPageActionsToggleLabel();
    updateAudioDiagnostic();
    initTrinkeySyncIndicator();
}

async function copyDiagnostics() {
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
}

window.addEventListener("keydown", (event) => {
    if (event.code === "AltLeft") {
        if (!leftAltDown) leftAltUsedWithPreview = false;
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
    leftAltUsedWithPreview = true;
    showSymbolPreview(symbol);
    socket.send(JSON.stringify({ action: "play-morse-repeat", symbol }));
});

window.addEventListener("keyup", (event) => {
    if (event.code === "AltLeft") {
        if (leftAltDown && !leftAltUsedWithPreview) {
            event.preventDefault();
            restartTrainingRun();
        }
        leftAltDown = false;
        leftAltUsedWithPreview = false;
    }
});

window.addEventListener("blur", () => {
    leftAltDown = false;
    leftAltUsedWithPreview = false;
    stopSequencePlayback();
    hideSymbolPreview();
});

initialiseTrainingInput();
installPlaybackControls();
installTrainingNavigationControls();
installKeyControls();
installClaimHandlers(sequenceRow, () => socket);
socket = connectKoch({
    onOpen() {
        recordDiagnostic("websocket", { state: "open", url: socket?.url || "" });
        socket.send(JSON.stringify({ action: "get-audio-settings" }));
        startBrowserMidi(socket);
    },
    onMessage: appendEvent,
    onClose() {
        recordDiagnostic("websocket", { state: "close", url: socket?.url || "" });
        hideSymbolPreview();
        sidetone.mute();
        clearBrowserMidiInput();
    },
});
