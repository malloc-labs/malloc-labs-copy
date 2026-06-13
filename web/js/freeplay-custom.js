// Freeplay custom-input + rhythm review.
//
// Owns the single-line "practice this" input that sits below the
// Sequence section on the Freeplay page, and renders a baseline review
// block matching Cadence's, scaled to the typed sequence. Subscribes to
// sent-symbol and key-input-start CustomEvents that key-timing.js
// dispatches; no direct coupling beyond the event names.

import {
    buildExerciseBlock,
    buildExpectedSteps,
    syncRhythmReviewPresentation,
} from "./rhythm-review.js";

const STORAGE_KEY = "copy-653.freeplay-custom-input";
const APPLY_DEBOUNCE_MS = 200;

const inputEl = document.getElementById("freeplay-custom-input");
const toggleEl = document.getElementById("freeplay-custom-toggle");
const arrowEl = document.getElementById("freeplay-custom-arrow");
const bodyEl = document.getElementById("freeplay-custom-body");
const labelEl = document.getElementById("freeplay-custom-label");
const reviewToggleEl = document.getElementById("key-rhythm-review-toggle");
const reviewArrowEl = document.getElementById("key-rhythm-review-arrow");
const reviewMetaEl = document.getElementById("key-rhythm-review-meta");
const reviewBodyEl = document.getElementById("key-rhythm-review-body");
const reviewSymbolsEl = document.getElementById("key-rhythm-review-symbols");
const reviewTabsEl = document.getElementById("key-rhythm-review-tabs");

// Bail if the custom-input markup isn't on this page — keeps this
// module a no-op when accidentally loaded somewhere else.
if (inputEl) initialise();

function initialise() {
    let exercise = "";
    let expectedSteps = [];
    let progress = 0;
    let events = [];
    let ditMs = 60;
    let applyTimer = null;

    const stored = loadStored();
    if (stored !== null) inputEl.value = stored;
    applyInputImmediate(inputEl.value);

    inputEl.addEventListener("input", () => {
        if (applyTimer !== null) clearTimeout(applyTimer);
        applyTimer = window.setTimeout(() => {
            applyTimer = null;
            saveStored(inputEl.value);
            applyInputImmediate(inputEl.value);
        }, APPLY_DEBOUNCE_MS);
    });

    document.addEventListener("copy-653:key-input-start", (event) => {
        const next = Number(event.detail?.ditMs);
        if (Number.isFinite(next) && next > 0) {
            ditMs = next;
            render();
        }
    });

    document.addEventListener("copy-653:sent-clear", () => {
        events = [];
        progress = 0;
        render();
    });

    document.addEventListener("copy-653:sent-symbol", (event) => {
        if (expectedSteps.length === 0) return;
        const detail = event.detail || {};
        const symbol = String(detail.symbol || "");
        const leadingGap = detail.leadingGap || "none";
        const leadingGapMs = detail.leadingGapMs;
        const attemptStart = isAttemptStart(symbol, leadingGap);
        events.push({
            symbol,
            leadingGap,
            leadingGapMs,
            isAttemptStart: attemptStart,
        });
        advanceProgress(symbol, leadingGap);
        render();
    });

    if (toggleEl) {
        toggleEl.addEventListener("click", () => {
            const expanded = toggleEl.getAttribute("aria-expanded") === "true";
            setSectionExpanded(!expanded);
        });
        renderToggleLabel();
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

    function applyInputImmediate(raw) {
        // Uppercase + collapse internal whitespace. Trim outer space so
        // a leading space doesn't introduce a phantom word-gap column.
        const normalised = (raw || "")
            .toUpperCase()
            .replace(/\s+/g, " ")
            .trim();
        exercise = normalised;
        expectedSteps = buildExpectedSteps(exercise);
        progress = 0;
        events = [];
        render();
    }

    function advanceProgress(symbol, leadingGap) {
        if (expectedSteps.length === 0) return;
        const expected = expectedSteps[progress];
        const symbolMatches = expected && symbol === expected.symbol;
        const gapMatches = progress === 0 || leadingGap === expected.leading;
        if (symbolMatches && gapMatches) {
            progress += 1;
            if (progress >= expectedSteps.length) progress = 0;
            return;
        }
        progress = symbol === expectedSteps[0].symbol ? 1 : 0;
    }

    function isAttemptStart(symbol, leadingGap) {
        if (expectedSteps.length === 0) return true;
        const stepZero = expectedSteps[0];
        if (!stepZero || symbol !== stepZero.symbol) return false;
        if (progress === 0) return true;
        const expected = expectedSteps[progress];
        const continuesCurrentStep =
            expected && symbol === expected.symbol && leadingGap === expected.leading;
        return !continuesCurrentStep;
    }

    function render() {
        if (!reviewSymbolsEl || !reviewMetaEl) return;
        reviewSymbolsEl.replaceChildren();
        if (reviewTabsEl) reviewTabsEl.replaceChildren();
        if (!exercise) {
            reviewMetaEl.textContent = "no input";
            syncRhythmReviewPresentation(null);
            return;
        }
        reviewMetaEl.textContent = "1 sequence";
        reviewSymbolsEl.appendChild(
            buildExerciseBlock({
                exercise,
                title: `Custom / ${exercise}`,
                ariaLabel: "Custom baseline",
                events,
                ditMs,
            }),
        );
        syncRhythmReviewPresentation(() => ({
            title: `Custom / ${exercise}`,
            content: buildExerciseBlock({
                exercise,
                title: `Custom / ${exercise}`,
                ariaLabel: "Custom expanded baseline",
                events,
                ditMs,
            }),
        }));
    }

    function setSectionExpanded(expanded) {
        if (!toggleEl || !arrowEl || !bodyEl) return;
        toggleEl.setAttribute("aria-expanded", String(expanded));
        arrowEl.textContent = expanded ? "▼" : "▶";
        bodyEl.hidden = !expanded;
        if (expanded) inputEl.focus();
    }

    function renderToggleLabel() {
        if (!labelEl || !toggleEl) return;
        const u = document.createElement("u");
        u.textContent = "i";
        labelEl.replaceChildren(u, document.createTextNode("nput"));
        toggleEl.title = "Show/hide custom input (I)";
        toggleEl.setAttribute("aria-keyshortcuts", "I");
    }
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
        // localStorage may be disabled (private mode, quota). Silent on
        // purpose — the in-memory state still drives this session.
    }
}
