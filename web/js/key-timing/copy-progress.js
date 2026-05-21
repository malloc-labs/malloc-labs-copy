// Copy — Key timing page copy-progress pipeline.
//
// Owns the entire learner-facing "what am I keying against what" loop:
// the engine-shipped exercise list, the per-exercise sent buckets that
// feed the rhythm-review, the step-walker that decides when a fresh
// attempt has begun, and the IMI ("Repeat; Say Again") cue. Renders
// the Sent line / Sent history list and orchestrates a sent-symbol
// event through diagnostics, the rhythm review, the HH-clear watcher,
// and the page-level fan-out CustomEvent.
//
// This module deliberately bundles copy-exercise tracking and sent-
// history because renderSentSymbol mutates both in lockstep —
// splitting them apart would have meant a cyclic import or a thicker
// orchestrator in the page controller.
//
// Cross-module reads (active socket, current key config, appendDiagnosticRow)
// land via installCopyProgressAccessors so this module never imports
// midi-input.js directly.

import { buildExpectedSteps } from "../rhythm-review.js";
import { noteSentSymbol, resetHHClearTracker } from "../hh-clear.js";
import { recordDiagnostic } from "./diagnostics.js";
import { renderRhythmReview, setSelectedReviewIndex } from "./review.js";
import {
    setCopyHistoryExpanded,
    setKeyPageActionsExpanded,
    setRhythmReviewExpanded,
    setSentExpanded,
    setSequenceExpanded,
} from "./collapsibles.js";
import {
    copyHistoryEl,
    copyImiEl,
    copyPositionLabelEl,
    copySymbolEl,
    diagGapEl,
    sentHistoryEl,
    sentSymbolEl,
} from "./dom.js";

const MAX_SENT_HISTORY = 48;

let copyExercises = [];
let selectedCopyIndex = 0;
// Per-step expectation: { symbol, leading } where leading is "none",
// "word", or "character" — same vocabulary the engine emits on
// sent-symbol events.
let expectedCopySteps = [];
let copyProgress = 0;
// Once the final exercise of the set is fully matched, the page
// stops processing further sent-symbol events until New requests a
// fresh set. The Trinkey/sidetone path is unaffected (the engine
// keeps decoding); we just refuse to attribute any further keying
// to the just-finished round so the Sent line and rhythm review do
// not accumulate post-completion noise. Cadence analysis on the
// engine side already ignores trailing events past the last matched
// target, so this flag is purely a UI concern.
let sessionComplete = false;
// One bucket of sent events per exercise (index-aligned to
// copyExercises). Filled live as sends arrive into the currently
// selected exercise; preserved across exercise selection so the
// learner can scroll the review and see prior attempts. Reset by
// the explicit "clear" button and when the engine ships a new
// exercise list.
let sentEventsByExercise = [];
let lastSentEndedAt = null;
let imiCueTimerId = null;
// Stamped on every browser-MIDI note-off (not lastSentEndedAt — that
// only updates after a successful decode, so a runaway concat would
// let the cue flash while the learner is still actively keying).
// Cleared to null on the next note-on.
let lastNoteOffAt = null;

let getActiveSocket = () => null;
let getKeyConfig = () => null;
let appendDiagnosticRow = () => {};

export function installCopyProgressAccessors(accessors) {
    getActiveSocket = accessors.activeSocket;
    getKeyConfig = accessors.keyConfig;
    appendDiagnosticRow = accessors.appendDiagnosticRow;
}

export function getCopyExercises() {
    return copyExercises;
}

export function getSentEventsByExercise() {
    return sentEventsByExercise;
}

// Browser-MIDI note-off bookkeeping for the IMI cue — midi-input.js
// calls this on every formed note-off; the cue's silence window is
// measured from this timestamp rather than from lastSentEndedAt so
// the cue can never flash while the learner is still actively keying.
export function setLastNoteOffAt(timestamp) {
    lastNoteOffAt = timestamp;
}

export function updateCopyPositionLabel() {
    if (!copyPositionLabelEl) return;
    const total = copyExercises.length;
    if (total === 0) {
        copyPositionLabelEl.textContent = "Exercise sequence:";
        return;
    }
    const position = Math.min(selectedCopyIndex + 1, total);
    copyPositionLabelEl.textContent = `Exercise sequence ${position}/${total}:`;
}

export function clearSentSymbols() {
    sentSymbolEl.textContent = "—";
    sentHistoryEl.replaceChildren();
    lastSentEndedAt = null;
    // Intentionally do NOT touch sentEventsByExercise or re-render the
    // review — clear is scoped to the Sent line so the review section
    // preserves prior attempts across clears.
    copyProgress = 0;
    clearImiCue();
    diagGapEl.textContent = "none";
    resetHHClearTracker();
    recordDiagnostic("sent-symbols-clear");
    // Fan-out for page-specific listeners. Freeplay extends clear to also
    // wipe its custom-input review block; the cadence page has no
    // listener, so its review is preserved as above.
    document.dispatchEvent(new CustomEvent("copy-653:sent-clear"));
}

export function requestCopyExercises() {
    if (!copyHistoryEl) return;
    const socket = getActiveSocket();
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ action: "request-copy-exercises" }));
    // A fresh set discards any in-flight state; collapse every
    // disclosure so the page returns to its default quiet layout.
    setSentExpanded(false);
    setSequenceExpanded(false);
    setKeyPageActionsExpanded(false);
    setCopyHistoryExpanded(false);
    setRhythmReviewExpanded(false);
}

function updateExpectedCopySteps() {
    expectedCopySteps = buildExpectedSteps(copyExercises[selectedCopyIndex]);
    copyProgress = 0;
}

// Full reset — used by session events (clear, exercise switch,
// completion) so the cue doesn't reappear after the context has
// moved on. Resets lastNoteOffAt so a stale note-off can't trigger
// the cue in the new context.
export function clearImiCue() {
    if (imiCueTimerId !== null) {
        clearTimeout(imiCueTimerId);
        imiCueTimerId = null;
    }
    lastNoteOffAt = null;
    if (copyImiEl) copyImiEl.hidden = true;
}

// Idempotent — recomputes the cue's pending-vs-visible state from
// current lastNoteOffAt. Called from note-off and whenever copyProgress
// changes via sent-symbol, so the cue tracks the actual silence window
// rather than the moment of any single event. Intentionally does not
// gate on copyProgress: after a runaway concat the decoder emits `?`
// and noteCopySymbolForProgress resets progress to 0, but the learner
// still needs the cue at that point — they were keying, they paused,
// they want to try again.
export function refreshImiCue() {
    if (imiCueTimerId !== null) {
        clearTimeout(imiCueTimerId);
        imiCueTimerId = null;
    }
    if (!copyImiEl) return;
    if (expectedCopySteps.length === 0 || lastNoteOffAt === null) {
        copyImiEl.hidden = true;
        return;
    }
    const ditMs = Number(getKeyConfig()?.dit_ms_expected) || 60;
    const wordGapMs = 7 * ditMs;
    const elapsed = performance.now() - lastNoteOffAt;
    if (elapsed >= wordGapMs) {
        copyImiEl.hidden = false;
        return;
    }
    copyImiEl.hidden = true;
    imiCueTimerId = window.setTimeout(() => {
        imiCueTimerId = null;
        if (expectedCopySteps.length === 0 || lastNoteOffAt === null) return;
        copyImiEl.hidden = false;
    }, wordGapMs - elapsed);
}

// Walk a single pointer through the expected steps. The first step
// accepts any leading gap (the learner could be starting fresh,
// mid-stream, or after a clear); every subsequent step requires both
// the symbol AND the leading gap to match — so "MUM" only passes for
// one-word keying, not "M UM".
function noteCopySymbolForProgress(symbol, leadingGap) {
    if (expectedCopySteps.length === 0) return;
    const expected = expectedCopySteps[copyProgress];
    const symbolMatches = symbol === expected.symbol;
    const gapMatches = copyProgress === 0 || leadingGap === expected.leading;

    if (symbolMatches && gapMatches) {
        copyProgress += 1;
        if (copyProgress >= expectedCopySteps.length) {
            copyProgress = 0;
            // Advance to the next exercise in the current set if any.
            // On the final exercise we deliberately stop — the learner
            // presses "new" (or N) to request a fresh set, which keeps
            // the last review intact until they decide to move on.
            if (selectedCopyIndex + 1 < copyExercises.length) {
                selectCopyExercise(selectedCopyIndex + 1);
            } else {
                sentSymbolEl.textContent = "Completed";
                // Auto-reveal the Sent history so the learner can scan
                // the final set of attempts without first hitting X.
                setSentExpanded(true);
                clearImiCue();
                // Freeze further sent-symbol processing until New
                // opens a fresh set — see sessionComplete declaration.
                sessionComplete = true;
                // Tell the engine to finalize the in-flight cadence
                // session right now so trailing keying (while the
                // learner reads the review) is not appended to the
                // record on disk. The next `request-copy-exercises`
                // opens a fresh session normally.
                const socket = getActiveSocket();
                if (socket && socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({ action: "complete-cadence-session" }));
                }
            }
        }
        refreshImiCue();
        return;
    }

    // Mismatch — fall back to step 0. If this symbol matches step 0's
    // symbol, count the current input as the start of a fresh attempt.
    copyProgress = symbol === expectedCopySteps[0].symbol ? 1 : 0;
    refreshImiCue();
}

// TODO(cadence): if the HH-clear dev toggle is on (Settings →
// Developer), keying "HH" clears the Sent area. The random exercises
// the engine emits can still contain "HH" — once H joins the claimed
// set, keying such an exercise as displayed would inadvertently clear
// the learner's work. Either filter incoming exercises here, or pass
// the toggle state up so the generator suppresses HH at source. See
// web/js/hh-clear.js.
export function renderCopyExercises(event) {
    if (!copyHistoryEl || !copySymbolEl) return;
    const exercises = Array.isArray(event.exercises) ? event.exercises : [];
    copyHistoryEl.replaceChildren();
    selectedCopyIndex = 0;
    setSelectedReviewIndex(0);
    copyExercises = exercises;
    sentEventsByExercise = exercises.map(() => []);
    updateExpectedCopySteps();
    clearImiCue();
    sessionComplete = false;
    if (exercises.length === 0) {
        copySymbolEl.textContent = "—";
        updateCopyPositionLabel();
        return;
    }
    exercises.forEach((exercise, idx) => {
        const item = document.createElement("li");
        item.className = "key-copy-history__item";
        item.dataset.exercise = exercise;
        if (idx === selectedCopyIndex) item.dataset.selected = "true";
        const row = document.createElement("div");
        row.className = "key-copy-history__row";
        const words = exercise.split(" ");
        words.forEach((word, wordIdx) => {
            for (let i = 0; i < word.length; i++) {
                const leading =
                    wordIdx === 0 && i === 0
                        ? "none"
                        : i === 0
                        ? "word"
                        : "character";
                const charEl = document.createElement("span");
                charEl.className =
                    `key-copy-history__symbol key-copy-history__symbol--leading-${leading}`;
                charEl.textContent = word[i];
                row.appendChild(charEl);
            }
        });
        item.appendChild(row);
        copyHistoryEl.appendChild(item);
    });
    copySymbolEl.textContent = exercises[selectedCopyIndex];
    updateCopyPositionLabel();
    renderRhythmReview();
}

export function selectCopyExercise(idx) {
    if (!copyHistoryEl || !copySymbolEl) return false;
    const items = copyHistoryEl.querySelectorAll(".key-copy-history__item");
    if (idx < 0 || idx >= items.length) return false;
    selectedCopyIndex = idx;
    setSelectedReviewIndex(idx);
    items.forEach((item, i) => {
        if (i === idx) item.dataset.selected = "true";
        else delete item.dataset.selected;
    });
    copySymbolEl.textContent = items[idx].dataset.exercise || "";
    updateExpectedCopySteps();
    clearImiCue();
    updateCopyPositionLabel();
    renderRhythmReview();
    return true;
}

// Predict whether the incoming event should start a new attempt row,
// using the same step-walking vocabulary as
// noteCopySymbolForProgress but called *before* that function mutates
// copyProgress. A new row is begun only when the event matches step 0
// of the exercise — either from a clean state (copyProgress === 0) or
// as a mid-stream restart where the user re-keys the exercise's first
// symbol while we'd been expecting a later step. Junk symbols that
// don't match step 0 append to the current row instead of fragmenting
// the display.
function isAttemptStartForEvent(symbol, leadingGap) {
    if (expectedCopySteps.length === 0) return true;
    const stepZero = expectedCopySteps[0];
    if (!stepZero || symbol !== stepZero.symbol) return false;
    if (copyProgress === 0) return true;
    // Mid-stream: only a restart if the current expected step isn't
    // also satisfied by this event (e.g., MUM at progress=2 expects M
    // and the user keys M — that's the legitimate finish, not a
    // restart).
    const expected = expectedCopySteps[copyProgress];
    const continuesCurrentStep =
        expected && symbol === expected.symbol && leadingGap === expected.leading;
    return !continuesCurrentStep;
}

export function clearCopyExercises() {
    if (!copyHistoryEl || !copySymbolEl) return;
    copySymbolEl.textContent = "—";
    copyHistoryEl.replaceChildren();
    selectedCopyIndex = 0;
    setSelectedReviewIndex(0);
    copyExercises = [];
    sentEventsByExercise = [];
    updateExpectedCopySteps();
    clearImiCue();
    sessionComplete = false;
    updateCopyPositionLabel();
    renderRhythmReview();
}

export function renderSentSymbol(event) {
    // Freeze post-completion until New opens a fresh set. The Sent
    // line, history list, diagnostics row, per-exercise bucket, and
    // rhythm-review are all skipped so the finished round's display
    // stays exactly as the learner left it.
    if (sessionComplete) return;
    const symbol = event.symbol || "?";
    const startedAt = Number(event.started_at);
    const endedAt = Number(event.ended_at);
    const leadingGapMs = Number.isFinite(startedAt) && Number.isFinite(lastSentEndedAt)
        ? Math.max(0, (startedAt - lastSentEndedAt) * 1000)
        : null;

    sentSymbolEl.textContent = symbol;
    diagGapEl.textContent = event.leading_gap || "none";
    recordDiagnostic("sent-symbol", {
        symbol,
        pattern: event.pattern,
        leading_gap: event.leading_gap || "none",
        leading_gap_ms: leadingGapMs,
        started_at: event.started_at,
        ended_at: event.ended_at,
    });
    appendDiagnosticRow(event);

    const item = document.createElement("li");
    const leading = event.leading_gap || "none";
    item.classList.add(`key-sent-history__item--leading-${leading}`);
    const symbolEl = document.createElement("span");
    symbolEl.className = "key-sent-history__symbol";
    symbolEl.textContent = symbol;
    item.append(symbolEl);
    sentHistoryEl.appendChild(item);

    while (sentHistoryEl.children.length > MAX_SENT_HISTORY) {
        sentHistoryEl.firstElementChild.remove();
    }

    if (Number.isFinite(endedAt)) {
        lastSentEndedAt = endedAt;
    }
    const bucket = sentEventsByExercise[selectedCopyIndex];
    if (bucket) {
        bucket.push({
            symbol,
            leadingGap: event.leading_gap || "none",
            leadingGapMs,
            // Computed against copyProgress *before*
            // noteCopySymbolForProgress runs below — true on the event
            // that begins a fresh walk through the exercise (progress
            // was 0) or on a mid-stream restart where the symbol
            // matches step 0 after a mismatch. The renderer segments
            // the bucket into rows on these boundaries.
            isAttemptStart: isAttemptStartForEvent(symbol, event.leading_gap || "none"),
        });
    }
    renderRhythmReview();
    noteSentSymbol(symbol, event.leading_gap, clearSentSymbols);
    noteCopySymbolForProgress(symbol, event.leading_gap || "none");
    // Fan-out for page-specific listeners (e.g. Freeplay's
    // custom-input review). Dispatched after the cadence pipeline has
    // finished so the shared state is consistent if a listener cares
    // to read it.
    document.dispatchEvent(new CustomEvent("copy-653:sent-symbol", {
        detail: {
            symbol,
            leadingGap: event.leading_gap || "none",
            leadingGapMs,
        },
    }));
}
