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
import { KOCH_ORDER } from "./partials/koch-sequence.js";
import { hideSymbolPreview, showSymbolPreview, symbolForPreviewCode } from "./symbol-preview.js";

const STORAGE_KEY = "copy-653.key-training-input";
const MODE_STORAGE_KEY = "copy-653.key-training-mode";
const APPLY_DEBOUNCE_MS = 150;
const DEFAULT_QUEUE = ["K"];
const STRUCTURED_EXERCISE_COUNT = 20;
const TRAINING_MODES = new Set(["custom", "scales", "intervals", "etudes"]);
const CHARACTER_GAP_EARLY_DITS = 1.0;
const CHARACTER_GAP_PASS_MIN_DITS = 2.0;
const CHARACTER_GAP_PASS_MAX_DITS = 5.0;
const CHARACTER_GAP_FAIL_DITS = 8.0; // raised from 6.0 — 6 dits still scores 0.5 on the cadence readability curve and is well within separable fist range; 8 dits aligns the hard-restart gate with the cadence zero-score boundary (7 dits) plus one dit of live-feedback margin
const WORD_GAP_EARLY_DITS = 5.0;
const WORD_GAP_PASS_DITS = 6.0;

const sequenceRow = document.getElementById("sequence-row");
const modeTabsEl = document.getElementById("training-mode-tabs");
const customSectionEl = document.querySelector(".training-custom-input");
const focusSectionEl = document.getElementById("training-focus");
const exercisesSectionEl = document.getElementById("training-exercises");
const exerciseTitleEl = document.getElementById("training-exercise-title");
const exerciseMetaEl = document.getElementById("training-exercise-meta");
const exerciseRestartEl = document.getElementById("training-exercise-restart");
const exercisePositionEl = document.getElementById("training-exercise-position");
const exerciseSequenceEl = document.getElementById("training-exercise-sequence");
const exerciseCompletedEl = document.getElementById("training-exercise-completed");
const exerciseListEl = document.getElementById("training-exercise-list");
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
let expectedDitMs = 60;
let expectedCharacterGapMs = 180;
let expectedWordGapMs = 420;
let trainingMode = "custom";
let symbolQueue = [...DEFAULT_QUEUE];
let structuredExercises = [];
let structuredExerciseRanges = [];
let structuredRunStarted = false;
let keyTrainingRecordActive = false;
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
let lastAcceptedSentEvent = null;
let structuredAttemptIndices = new Map();
let lineFaultIndices = new Map(); // symbolQueue index → "timing-fail" | "wrong-symbol"
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
    return expectedDitMs;
}

function updateExpectedTiming(event) {
    const nextWpm = Number(event.character_wpm ?? event.character_speed_wpm);
    if (Number.isFinite(nextWpm) && nextWpm > 0) {
        characterWpm = nextWpm;
    }

    const nextDitMs = Number(event.dit_ms_expected);
    if (Number.isFinite(nextDitMs) && nextDitMs > 0) {
        expectedDitMs = nextDitMs;
    } else {
        expectedDitMs = 1200 / Math.max(1, characterWpm);
    }

    const nextCharacterGapMs = Number(event.character_gap_ms);
    expectedCharacterGapMs = Number.isFinite(nextCharacterGapMs) && nextCharacterGapMs > 0
        ? nextCharacterGapMs
        : 3 * expectedDitMs;

    const nextWordGapMs = Number(event.word_gap_ms);
    expectedWordGapMs = Number.isFinite(nextWordGapMs) && nextWordGapMs > 0
        ? nextWordGapMs
        : 7 * expectedDitMs;
}

function appendEvent(event) {
    if (event.type === "claimed-symbols") {
        claimedSymbolSet = renderSequence(sequenceRow, event);
        if (isStructuredMode()) regenerateStructuredExercises();
        return;
    }
    if (event.type === "audio-settings") {
        keyerMode = event.keyer_mode || keyerMode;
        updateExpectedTiming(event);
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
        updateExpectedTiming(event);
        renderKeyInputStart(event);
        renderStructuredExercises();
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
        lastAcceptedSentEvent = null;
        renderKeyInputReset(event);
        renderTrainingFocus();
        return;
    }
    if (event.type === "sent-symbol") {
        appendDiagnosticRow(event);
        captureObservedAttempt(event);
        noteTrainingAttempt(event);
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

function initialiseTrainingModes() {
    const stored = loadStoredMode();
    trainingMode = TRAINING_MODES.has(stored) ? stored : "custom";

    if (modeTabsEl) {
        modeTabsEl.querySelectorAll("[data-training-mode]").forEach((tab) => {
            tab.addEventListener("click", () => {
                const mode = tab.getAttribute("data-training-mode");
                if (mode && TRAINING_MODES.has(mode)) setTrainingMode(mode);
            });
        });
    }

    renderTrainingMode();
    if (isStructuredMode()) regenerateStructuredExercises();
}

function setTrainingMode(mode) {
    if (!TRAINING_MODES.has(mode) || mode === trainingMode) return;
    stopSequencePlayback();
    abortKeyTrainingRecord();
    trainingMode = mode;
    saveStoredMode(mode);
    renderTrainingMode();
    if (isStructuredMode()) {
        regenerateStructuredExercises();
    } else {
        applyInputImmediate(inputEl?.value || "");
    }
}

function renderTrainingMode() {
    if (modeTabsEl) {
        modeTabsEl.querySelectorAll("[data-training-mode]").forEach((tab) => {
            const selected = tab.getAttribute("data-training-mode") === trainingMode;
            tab.setAttribute("aria-selected", String(selected));
            tab.dataset.active = String(selected);
        });
    }
    if (customSectionEl) customSectionEl.hidden = isStructuredMode();
    if (focusSectionEl) focusSectionEl.hidden = isStructuredMode();
    if (exercisesSectionEl) exercisesSectionEl.hidden = !isStructuredMode();
}

function isStructuredMode() {
    return trainingMode !== "custom";
}

function applyInputImmediate(raw) {
    if (isStructuredMode()) return;
    if (playSequenceEl?.dataset.playing === "true") stopSequencePlayback();
    const nextQueue = normaliseSymbols(raw);
    symbolQueue = nextQueue.length ? nextQueue : [...DEFAULT_QUEUE];
    structuredExercises = [];
    structuredExerciseRanges = [];
    structuredRunStarted = false;
    activeIndex = firstSymbolIndex(symbolQueue);
    completedThroughIndex = -1;
    lastKeyedSymbol = "";
    lastAcceptedSentEvent = null;
    structuredAttemptIndices = new Map();
    pendingObservedElements = [];
    observedAttemptsByIndex = new Map();
    renderTrainingFocus();
    renderLastKeyed();
}

function regenerateStructuredExercises() {
    const exercises = buildStructuredExercises(trainingMode, trainingSymbols());
    applyStructuredExercises(exercises);
}

function applyStructuredExercises(exercises) {
    stopSequencePlayback();
    abortKeyTrainingRecord();
    structuredExercises = exercises;
    const flattened = [];
    structuredExerciseRanges = [];
    exercises.forEach((exercise) => {
        if (flattened.length > 0) flattened.push(" ");
        const start = flattened.length;
        flattened.push(...normaliseSymbols(exercise));
        const end = flattened.length - 1;
        structuredExerciseRanges.push({ start, end });
    });
    symbolQueue = flattened.length ? flattened : [...DEFAULT_QUEUE];
    structuredRunStarted = false;
    keyTrainingRecordActive = false;
    activeIndex = firstSymbolIndex(symbolQueue);
    completedThroughIndex = -1;
    lastKeyedSymbol = "";
    lastAcceptedSentEvent = null;
    structuredAttemptIndices = new Map();
    pendingObservedElements = [];
    observedAttemptsByIndex = new Map();
    renderTrainingFocus();
    renderLastKeyed();
    renderStructuredExercises();
}

function trainingSymbols() {
    const symbols = KOCH_ORDER.filter((symbol) => claimedSymbolSet.has(symbol) && PATTERNS[symbol]);
    return symbols.length ? symbols : [...DEFAULT_QUEUE];
}

function buildStructuredExercises(mode, symbols) {
    if (mode === "intervals") return buildIntervalExercises(symbols);
    if (mode === "etudes") return buildEtudeExercises(symbols);
    return buildScaleExercises(symbols);
}

function buildScaleExercises(symbols) {
    return Array.from({ length: STRUCTURED_EXERCISE_COUNT }, (_, idx) => {
        const symbol = symbols[idx % symbols.length];
        const form = idx % 3;
        if (form === 1) return `${symbol}${symbol} ${symbol}${symbol}`;
        if (form === 2) return `${symbol}${symbol}${symbol} ${symbol}${symbol}${symbol}`;
        return `${symbol} ${symbol} ${symbol} ${symbol}`;
    });
}

function buildIntervalExercises(symbols) {
    const pairs = [];
    if (symbols.length === 1) {
        pairs.push([symbols[0], symbols[0]]);
    } else {
        symbols.forEach((symbol, idx) => {
            const next = symbols[(idx + 1) % symbols.length];
            pairs.push([symbol, next], [next, symbol]);
        });
    }
    return Array.from({ length: STRUCTURED_EXERCISE_COUNT }, (_, idx) => {
        const [a, b] = pairs[idx % pairs.length];
        const form = idx % 3;
        if (form === 1) return `${a}${b} ${a}${b}`;
        if (form === 2) return `${a}${b}${a} ${a}${b}${a}`;
        return `${a} ${b} ${a} ${b}`;
    });
}

function buildEtudeExercises(symbols) {
    const curated = [
        "CQ CQ CQ",
        "BK BK BK",
        "DE DE",
        "DE MM7KMU DE MM7KMU",
    ].filter((exercise) => normaliseSymbols(exercise).every((symbol) => (
        symbol === " " || symbols.includes(symbol)
    )));
    const generated = Array.from({ length: STRUCTURED_EXERCISE_COUNT }, (_, idx) => {
        const width = Math.min(symbols.length, 2 + (idx % 4));
        const start = idx % symbols.length;
        const word = Array.from({ length: width }, (_unused, offset) => (
            symbols[(start + offset) % symbols.length]
        )).join("");
        const repeat = idx % 3 === 0 ? 3 : 2;
        return Array.from({ length: repeat }, () => word).join(" ");
    });
    return [...curated, ...generated].slice(0, STRUCTURED_EXERCISE_COUNT);
}

function renderStructuredExercises() {
    if (!isStructuredMode()) return;
    if (exerciseTitleEl) exerciseTitleEl.textContent = modeTitle(trainingMode);
    if (exerciseMetaEl) {
        exerciseMetaEl.textContent = `${structuredExercises.length} exercises · ${trainingSymbols().length} symbols`;
    }
    if (exerciseListEl) {
        exerciseListEl.replaceChildren();
        structuredExercises.forEach((exercise, idx) => {
            const item = document.createElement("li");
            item.className = "key-training-exercises__item";
            item.dataset.exerciseIndex = String(idx);
            const isActive = idx === currentStructuredExerciseIndex();
            const isCompleted = structuredExerciseCompleted(idx);
            item.dataset.active = String(isActive);
            item.dataset.completed = String(isCompleted);
            item.dataset.future = String(!isActive && !isCompleted);
            const number = document.createElement("span");
            number.className = "key-training-exercises__number";
            number.textContent = String(idx + 1).padStart(2, "0");
            const target = document.createElement("button");
            target.type = "button";
            target.className = "key-training-exercises__target-button";
            appendExerciseGlyphs(target, exercise, structuredExerciseRanges[idx]);
            target.addEventListener("click", () => {
                const range = structuredExerciseRanges[idx];
                if (!range) return;
                activeIndex = firstSymbolIndexInRange(range);
                renderTrainingFocus();
            });
            item.append(number, target);
            exerciseListEl.appendChild(item);
        });
    }
    const idx = currentStructuredExerciseIndex();
    const displayIdx = Math.max(0, Math.min(idx, structuredExercises.length - 1));
    if (exercisePositionEl) {
        exercisePositionEl.textContent = structuredExercises.length
            ? `Exercise ${displayIdx + 1}/${structuredExercises.length}`
            : "No exercises";
    }
    if (exerciseSequenceEl) {
        exerciseSequenceEl.replaceChildren();
        const exercise = structuredExercises[displayIdx];
        const range = structuredExerciseRanges[displayIdx];
        if (exercise && range) {
            appendExerciseGlyphs(exerciseSequenceEl, exercise, range);
        } else {
            exerciseSequenceEl.textContent = "—";
        }
    }
    if (exerciseRestartEl) {
        exerciseRestartEl.textContent = structuredRunStarted ? "Restart" : "Start";
    }
    if (exerciseCompletedEl) {
        exerciseCompletedEl.hidden = !trainingSequenceCompleted();
    }
}

function appendExerciseGlyphs(parent, exercise, range) {
    if (!range) {
        parent.textContent = exercise || "—";
        return;
    }
    const focusIndex = playbackIndex ?? activeIndex;
    let tokenIndex = range.start;
    normaliseSymbols(exercise).forEach((token) => {
        const span = document.createElement("span");
        span.className = token === " "
            ? "key-training-exercises__glyph key-training-exercises__glyph--space"
            : "key-training-exercises__glyph";
        span.dataset.completed = String(tokenIndex <= completedThroughIndex);
        span.dataset.fault = lineFaultIndices.get(tokenIndex) || "";
        span.dataset.active = String(tokenIndex === focusIndex);
        span.textContent = token === " " ? " " : token;
        parent.appendChild(span);
        tokenIndex += 1;
    });
}

function currentStructuredExerciseIndex() {
    const focusIndex = Math.min(
        playbackIndex ?? activeIndex,
        Math.max(0, symbolQueue.length - 1),
    );
    const idx = structuredExerciseRanges.findIndex((range) => (
        focusIndex >= range.start && focusIndex <= range.end
    ));
    if (idx !== -1) return idx;
    if (trainingSequenceCompleted()) return Math.max(0, structuredExercises.length - 1);
    return 0;
}

function structuredExerciseIndexForToken(tokenIndex) {
    const idx = structuredExerciseRanges.findIndex((range) => (
        tokenIndex >= range.start && tokenIndex <= range.end
    ));
    return idx === -1 ? currentStructuredExerciseIndex() : idx;
}

function structuredExerciseCompleted(idx) {
    const range = structuredExerciseRanges[idx];
    return range ? completedThroughIndex >= range.end : false;
}

function firstSymbolIndexInRange(range) {
    for (let idx = range.start; idx <= range.end; idx += 1) {
        if (symbolQueue[idx] !== " ") return idx;
    }
    return range.start;
}

function modeTitle(mode) {
    if (mode === "intervals") return "Intervals";
    if (mode === "etudes") return "Etudes";
    return "Scales";
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
    renderStructuredExercises();
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
        btn.dataset.fault = lineFaultIndices.get(idx) || "";
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
    structuredRunStarted = isStructuredMode() ? true : structuredRunStarted;
    activeIndex = firstSymbolIndex(symbolQueue);
    completedThroughIndex = -1;
    lastKeyedSymbol = "";
    lastAcceptedSentEvent = null;
    structuredAttemptIndices = new Map();
    lineFaultIndices = new Map();
    pendingObservedElements = [];
    observedAttemptsByIndex = new Map();
    renderTrainingFocus();
    renderLastKeyed();
}

async function startOrRestartStructuredRun() {
    if (!isStructuredMode()) {
        restartTrainingRun();
        return;
    }
    await enableSidetone();
    startKeyTrainingRecord();
    structuredRunStarted = true;
    activeIndex = firstSymbolIndex(symbolQueue);
    completedThroughIndex = -1;
    lastKeyedSymbol = "";
    lastAcceptedSentEvent = null;
    structuredAttemptIndices = new Map();
    lineFaultIndices = new Map();
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

function noteTrainingAttempt(event) {
    const symbol = event?.symbol;
    const pattern = typeof event?.pattern === "string" ? event.pattern : "";
    if (!symbol) {
        if (!pattern) return;
        lastKeyedSymbol = `Unreadable (${pattern})`;
        renderLastKeyed();

        if (isStructuredMode() && structuredRunStarted) {
            // Unreadable pattern: the decoder saw keying, but it did not map
            // to a symbol. Mark the current target, let the operator finish
            // the line, then restart the exercise at line end.
            lineFaultIndices.set(activeIndex, "invalid-pattern");
            recordTrainingAttempt(event, {
                expectedGap: expectedLeadingGap(activeIndex),
                spacing: { result: "not-evaluated" },
                result: "invalid-pattern",
                action: "taint-line",
            });

            const nextIndexAfterInvalid = nextSymbolIndex(symbolQueue, activeIndex + 1);
            const currentExerciseIdxAfterInvalid = currentStructuredExerciseIndex();
            const nextExerciseIdxAfterInvalid = nextIndexAfterInvalid !== -1
                ? structuredExerciseIndexForToken(nextIndexAfterInvalid)
                : currentExerciseIdxAfterInvalid;
            const isLastSymbolInExercise = nextIndexAfterInvalid === -1
                || nextExerciseIdxAfterInvalid !== currentExerciseIdxAfterInvalid;
            if (isLastSymbolInExercise) {
                recordTrainingAttempt(event, {
                    expectedGap: expectedLeadingGap(activeIndex),
                    spacing: { result: "not-evaluated" },
                    result: "invalid-pattern",
                    action: "restart-line",
                });
                lastAcceptedSentEvent = event;
                incrementStructuredAttempt(currentExerciseIdxAfterInvalid);
                restartStructuredLine(currentExerciseIdxAfterInvalid);
            } else {
                completedThroughIndex = nextIndexAfterInvalid - 1;
                activeIndex = nextIndexAfterInvalid;
                lastAcceptedSentEvent = event;
            }
        }
        renderTrainingFocus();
        return;
    }
    lastKeyedSymbol = String(symbol).toUpperCase();
    renderLastKeyed();

    if (isStructuredMode() && !structuredRunStarted) {
        renderTrainingFocus();
        return;
    }

    const target = symbolQueue[activeIndex];
    if (target !== lastKeyedSymbol) {
        if (isStructuredMode()) {
            // Wrong symbol: taint the line so it will restart at completion,
            // but do not interrupt the operator mid-send.
            lineFaultIndices.set(activeIndex, "wrong-symbol");
            recordTrainingAttempt(event, {
                expectedGap: expectedLeadingGap(activeIndex),
                spacing: { result: "not-evaluated" },
                result: "wrong-symbol",
                action: "taint-line",
            });
        }
        renderTrainingFocus();
        return;
    }

    const spacing = isStructuredMode() ? targetSpacingResult(event) : { result: "pass" };
    if (spacing.result === "fail") {
        // Timing fail: taint the line and continue — restart deferred to line end.
        lineFaultIndices.set(activeIndex, "timing-fail");
        recordTrainingAttempt(event, {
            expectedGap: spacing.expected,
            spacing,
            result: "timing-fail",
            action: "taint-line",
        });
        // Advance past this symbol so the operator can complete the line.
        const nextIndexAfterFail = nextSymbolIndex(symbolQueue, activeIndex + 1);
        const currentExerciseIdxAfterFail = currentStructuredExerciseIndex();
        const nextExerciseIdxAfterFail = nextIndexAfterFail !== -1
            ? structuredExerciseIndexForToken(nextIndexAfterFail)
            : currentExerciseIdxAfterFail;
        const isLastSymbolInExercise = nextIndexAfterFail === -1 || nextExerciseIdxAfterFail !== currentExerciseIdxAfterFail;
        if (isLastSymbolInExercise) {
            // This was the last symbol in the exercise and it had a timing fault.
            // Use the same deferred-restart path as a clean line-end with a fault:
            // record the attempt then restart so the operator always finishes the
            // line before the reset fires.
            recordTrainingAttempt(event, {
                expectedGap: spacing.expected || "any",
                spacing,
                result: "timing-fail",
                action: "restart-line",
            });
            lastAcceptedSentEvent = event;
            incrementStructuredAttempt(currentExerciseIdxAfterFail);
            restartStructuredLine(currentExerciseIdxAfterFail);
        } else {
            completedThroughIndex = nextIndexAfterFail - 1;
            activeIndex = nextIndexAfterFail;
            lastAcceptedSentEvent = event;
        }
        renderTrainingFocus();
        return;
    }

    const nextIndex = nextSymbolIndex(symbolQueue, activeIndex + 1);
    const currentExerciseIdx = currentStructuredExerciseIndex();
    const nextExerciseIdx = nextIndex !== -1
        ? structuredExerciseIndexForToken(nextIndex)
        : currentExerciseIdx;
    const isLineEnd = nextIndex === -1 || nextExerciseIdx !== currentExerciseIdx;

    if (isLineEnd) {
        // Reached the natural end of this exercise line.
        const lineHasFault = [...lineFaultIndices.keys()].some((idx) => {
            const range = currentStructuredRange();
            return range && idx >= range.start && idx <= range.end;
        });
        if (lineHasFault) {
            // Record this final accepted symbol, then restart the line.
            recordTrainingAttempt(event, {
                expectedGap: spacing.expected || "any",
                spacing,
                result: "accepted",
                action: "restart-line",
            });
            lastAcceptedSentEvent = event;
            incrementStructuredAttempt(currentExerciseIdx);
            restartStructuredLine(currentExerciseIdx);
        } else if (nextIndex === -1) {
            recordTrainingAttempt(event, {
                expectedGap: spacing.expected || "any",
                spacing,
                result: "accepted",
                action: "complete-session",
            });
            completedThroughIndex = symbolQueue.length - 1;
            activeIndex = symbolQueue.length;
            lastAcceptedSentEvent = event;
            completeKeyTrainingRecord();
        } else {
            recordTrainingAttempt(event, {
                expectedGap: spacing.expected || "any",
                spacing,
                result: "accepted",
                action: "complete-exercise",
            });
            completedThroughIndex = nextIndex - 1;
            activeIndex = nextIndex;
            lastAcceptedSentEvent = event;
            // Reset decoder at exercise boundary so squeeze-tail artefacts
            // from the completed exercise don't bleed into the next one.
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: "reset-key-input", reason: "exercise-boundary" }));
            }
        }
    } else {
        recordTrainingAttempt(event, {
            expectedGap: spacing.expected || "any",
            spacing,
            result: "accepted",
            action: "advance",
        });
        completedThroughIndex = nextIndex - 1;
        activeIndex = nextIndex;
        lastAcceptedSentEvent = event;
    }
    renderTrainingFocus();
}

function recordTrainingAttempt(event, { expectedGap, spacing, result, action }) {
    if (!isStructuredMode() || !structuredRunStarted) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const exerciseIndex = currentStructuredExerciseIndex();
    const range = structuredExerciseRanges[exerciseIndex];
    const targetSymbol = symbolQueue[activeIndex] || "";
    const payload = {
        exercise_index: exerciseIndex + 1,
        target: structuredExercises[exerciseIndex] || "",
        attempt_index: structuredAttemptIndex(exerciseIndex),
        target_token_index: range ? symbolOrdinalInRange(activeIndex, range) : null,
        target_symbol: targetSymbol,
        sent_symbol: event?.symbol || null,
        pattern: event?.pattern || "",
        started_at: event?.started_at ?? null,
        ended_at: event?.ended_at ?? null,
        expected_gap: expectedGap || "any",
        decoder_gap: event?.leading_gap || "none",
        spacing_result: spacing?.result || "not-evaluated",
        result,
        action,
    };
    if (Number.isFinite(spacing?.gapMs)) {
        payload.gap_ms = Math.round(spacing.gapMs * 1000) / 1000;
    }
    if (Number.isFinite(spacing?.gapDits)) {
        payload.gap_dits = Math.round(spacing.gapDits * 1000) / 1000;
    }
    socket.send(JSON.stringify({
        action: "record-key-training-attempt",
        attempt: payload,
    }));
}

function structuredAttemptIndex(exerciseIndex) {
    const existing = structuredAttemptIndices.get(exerciseIndex);
    if (Number.isInteger(existing) && existing > 0) return existing;
    structuredAttemptIndices.set(exerciseIndex, 1);
    return 1;
}

function incrementStructuredAttempt(exerciseIndex) {
    structuredAttemptIndices.set(exerciseIndex, structuredAttemptIndex(exerciseIndex) + 1);
}

function symbolOrdinalInRange(index, range) {
    if (!range || index < range.start || index > range.end) return null;
    let ordinal = 0;
    for (let idx = range.start; idx <= index; idx += 1) {
        if (symbolQueue[idx] !== " ") ordinal += 1;
    }
    return ordinal;
}

function targetSpacingResult(event) {
    const expected = expectedLeadingGap(activeIndex);
    if (expected === "any") return { result: "pass", expected };
    const gapMs = measuredLeadingGapMs(event);
    if (!Number.isFinite(gapMs)) {
        const actual = event?.leading_gap || "none";
        return {
            result: actual === expected ? "pass" : "fail",
            expected,
            actual,
        };
    }

    const gapDits = gapMs / Math.max(1, expectedDitMs);
    const actual = event?.leading_gap || "none";
    const result = classifySpacingGap(expected, gapDits);
    return {
        result,
        expected,
        actual,
        gapMs,
        gapDits,
    };
}

function measuredLeadingGapMs(event) {
    const previousEnd = Number(lastAcceptedSentEvent?.ended_at);
    const currentStart = Number(event?.started_at);
    if (!Number.isFinite(previousEnd) || !Number.isFinite(currentStart)) return null;
    return Math.max(0, (currentStart - previousEnd) * 1000);
}

function classifySpacingGap(expected, gapDits) {
    if (!Number.isFinite(gapDits)) return "fail";
    if (expected === "character") {
        if (gapDits < CHARACTER_GAP_EARLY_DITS) return "fail";
        if (gapDits < CHARACTER_GAP_PASS_MIN_DITS) return "early";
        if (gapDits <= CHARACTER_GAP_PASS_MAX_DITS) return "pass";
        if (gapDits < CHARACTER_GAP_FAIL_DITS) return "late";
        return "fail";
    }
    if (expected === "word") {
        if (gapDits < WORD_GAP_EARLY_DITS) return "fail";
        if (gapDits < WORD_GAP_PASS_DITS) return "early";
        return "pass";
    }
    return "pass";
}

function expectedLeadingGap(index) {
    const range = currentStructuredRange();
    if (!range || index <= range.start) return "any";
    const previous = previousSymbolIndex(symbolQueue, index - 1);
    if (previous < range.start) return "any";
    for (let idx = previous + 1; idx < index; idx += 1) {
        if (symbolQueue[idx] === " ") return "word";
    }
    return "character";
}

function restartStructuredLine(exerciseIndex = currentStructuredExerciseIndex()) {
    const range = structuredExerciseRanges[exerciseIndex];
    if (!range) {
        restartTrainingRun();
        return;
    }
    // Clear only the fault markers that belong to this exercise range.
    for (const idx of lineFaultIndices.keys()) {
        if (idx >= range.start && idx <= range.end) lineFaultIndices.delete(idx);
    }
    activeIndex = firstSymbolIndexInRange(range);
    completedThroughIndex = range.start - 1;
    lastAcceptedSentEvent = null;
    pendingObservedElements = [];
    observedAttemptsByIndex = new Map();
    // Reset the server-side decoder so any iambic squeeze-tail artefact
    // accumulated during the just-completed line is discarded before the
    // first element of the repeated line arrives.
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ action: "reset-key-input", reason: "exercise-boundary" }));
    }
    renderTrainingFocus();
}

function currentStructuredRange() {
    return structuredExerciseRanges[currentStructuredExerciseIndex()] || null;
}

function startKeyTrainingRecord() {
    if (!isStructuredMode() || !socket || socket.readyState !== WebSocket.OPEN) return;
    if (keyTrainingRecordActive) abortKeyTrainingRecord();
    socket.send(JSON.stringify({
        action: "start-key-training-session",
        training_mode: trainingMode,
        exercises: structuredExercises,
        source_symbols: trainingSymbols(),
    }));
    keyTrainingRecordActive = true;
}

function completeKeyTrainingRecord() {
    if (!keyTrainingRecordActive || !socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ action: "complete-key-training-session" }));
    keyTrainingRecordActive = false;
}

function abortKeyTrainingRecord() {
    if (!keyTrainingRecordActive || !socket || socket.readyState !== WebSocket.OPEN) {
        keyTrainingRecordActive = false;
        return;
    }
    socket.send(JSON.stringify({ action: "abort-key-training-session" }));
    keyTrainingRecordActive = false;
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
    if (exerciseRestartEl) {
        exerciseRestartEl.addEventListener("click", startOrRestartStructuredRun);
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
            if (isStructuredMode()) {
                startOrRestartStructuredRun();
            } else {
                restartTrainingRun();
            }
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

function loadStoredMode() {
    try {
        return window.localStorage.getItem(MODE_STORAGE_KEY);
    } catch (_err) {
        return null;
    }
}

function saveStoredMode(value) {
    try {
        window.localStorage.setItem(MODE_STORAGE_KEY, value || "custom");
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
initialiseTrainingModes();
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
