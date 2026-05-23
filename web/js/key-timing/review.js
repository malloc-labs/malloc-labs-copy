// Copy — Key timing page rhythm-review section.
//
// Renders the rhythm review as a tab bar (one tab per exercise) plus
// the selected exercise's baseline block. Each block carries one
// column per symbol (asymmetric green|amber|red zone group, fixed
// width per column), and any sent symbols overlaid beneath as an
// up-arrow + glyph at a continuous x-fraction. x=0 is a perfectly-
// timed leading gap relative to the column's *baseline-expected* gap
// (not the engine's runtime classification); x rises into amber/red
// as the gap stretches. dit_ms_expected from key-input-start is the
// source of truth for the ideal gap math.
//
// Freeplay drives its own review pipeline from the custom-input
// textbox (freeplay-custom.js); this module no-ops when the Copy
// section isn't present.
//
// The page controller still owns the live copyExercises /
// sentEventsByExercise / keyConfig state. We read them through
// accessor callbacks installed at startup so the same source of truth
// is preserved.

import { buildExerciseBlock } from "../rhythm-review.js";
import {
    copyHistoryEl,
    rhythmReviewMetaEl,
    rhythmReviewSymbolsEl,
    rhythmReviewTabsEl,
} from "./dom.js";

let selectedReviewIndex = 0;
let getExercises = () => [];
let getSentEvents = () => [];
let getKeyConfig = () => null;

export function installReviewAccessors(accessors) {
    getExercises = accessors.exercises;
    getSentEvents = accessors.sentEvents;
    getKeyConfig = accessors.keyConfig;
}

export function setSelectedReviewIndex(idx) {
    selectedReviewIndex = idx;
}

export function renderRhythmReview() {
    if (!rhythmReviewSymbolsEl || !rhythmReviewMetaEl) return;
    // Freeplay has its own review pipeline (driven by the custom-input
    // textbox); leave the section alone so freeplay-custom.js owns it.
    // Copy Key has no copyHistoryEl but does use this review path.
    const isCopyKey = !!document.querySelector(".copy-key-shell");
    if (!copyHistoryEl && !isCopyKey) return;
    rhythmReviewSymbolsEl.replaceChildren();
    if (rhythmReviewTabsEl) rhythmReviewTabsEl.replaceChildren();

    const exercises = getExercises();
    const validIndices = exercises
        .map((ex, idx) => (ex && ex.length > 0 ? idx : -1))
        .filter((idx) => idx >= 0);
    rhythmReviewMetaEl.textContent =
        validIndices.length === 0
            ? "no exercises"
            : `${validIndices.length} ${validIndices.length === 1 ? "exercise" : "exercises"}`;

    if (validIndices.length === 0) return;

    if (!validIndices.includes(selectedReviewIndex)) {
        selectedReviewIndex = validIndices[0];
    }

    if (rhythmReviewTabsEl) {
        validIndices.forEach((exIdx, tabIdx) => {
            const exercise = exercises[exIdx];
            const tab = document.createElement("button");
            tab.type = "button";
            tab.className = "key-rhythm-review__tab";
            tab.role = "tab";
            tab.textContent = `${tabIdx + 1} / ${exercise}`;
            tab.title = exercise;
            const isSelected = exIdx === selectedReviewIndex;
            tab.setAttribute("aria-selected", String(isSelected));
            if (isSelected) tab.dataset.selected = "true";
            tab.addEventListener("click", () => {
                if (selectedReviewIndex === exIdx) return;
                selectedReviewIndex = exIdx;
                renderRhythmReview();
            });
            rhythmReviewTabsEl.appendChild(tab);
        });
    }

    const keyConfig = getKeyConfig();
    const ditMs = Number(keyConfig && keyConfig.dit_ms_expected) || 60;
    const exercise = exercises[selectedReviewIndex];
    const events = getSentEvents()[selectedReviewIndex] || [];
    rhythmReviewSymbolsEl.appendChild(
        buildExerciseBlock({
            exercise,
            title: `Exercise ${selectedReviewIndex + 1} / ${exercise}`,
            ariaLabel: `Exercise ${selectedReviewIndex + 1} baseline`,
            events,
            ditMs,
        }),
    );
}
