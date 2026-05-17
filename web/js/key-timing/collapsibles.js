// Copy — Key timing page collapsible sections.
//
// Five disclosure widgets share an identical pattern: an aria-expanded
// toggle button, an arrow glyph (▶ / ▼), and a body that's `hidden`
// when collapsed. Each section also owns an accelerator label rendered
// next to the title with the underlined hotkey letter.
//
// Cadence has all five; Freeplay only has rhythm-review. Every helper
// no-ops when its elements are missing so the same module can be loaded
// from either page.

import { makeAccelLabel } from "./utils.js";
import {
    copyHistoryArrowEl,
    copyHistoryEl,
    copyHistoryToggleEl,
    keyPageActionsArrowEl,
    keyPageActionsItemsEl,
    keyPageActionsToggleEl,
    rhythmReviewArrowEl,
    rhythmReviewBodyEl,
    rhythmReviewToggleEl,
    sentArrowEl,
    sentBodyEl,
    sentToggleEl,
    sequenceArrowEl,
    sequenceRow,
    sequenceToggleEl,
} from "./dom.js";

export function setRhythmReviewExpanded(expanded) {
    if (!rhythmReviewToggleEl || !rhythmReviewArrowEl || !rhythmReviewBodyEl) return;
    rhythmReviewToggleEl.setAttribute("aria-expanded", String(expanded));
    rhythmReviewArrowEl.textContent = expanded ? "▼" : "▶";
    rhythmReviewBodyEl.hidden = !expanded;
}

export function setCopyHistoryExpanded(expanded) {
    if (!copyHistoryToggleEl || !copyHistoryArrowEl || !copyHistoryEl) return;
    copyHistoryToggleEl.setAttribute("aria-expanded", String(expanded));
    copyHistoryArrowEl.textContent = expanded ? "▼" : "▶";
    copyHistoryEl.hidden = !expanded;
}

export function setSequenceExpanded(expanded) {
    if (!sequenceToggleEl || !sequenceArrowEl || !sequenceRow) return;
    sequenceToggleEl.setAttribute("aria-expanded", String(expanded));
    sequenceArrowEl.textContent = expanded ? "▼" : "▶";
    sequenceRow.hidden = !expanded;
}

export function setKeyPageActionsExpanded(expanded) {
    if (!keyPageActionsToggleEl || !keyPageActionsArrowEl || !keyPageActionsItemsEl) return;
    keyPageActionsToggleEl.setAttribute("aria-expanded", String(expanded));
    keyPageActionsArrowEl.textContent = expanded ? "▼" : "▶";
    keyPageActionsItemsEl.hidden = !expanded;
}

export function setSentExpanded(expanded) {
    if (!sentToggleEl || !sentArrowEl || !sentBodyEl) return;
    sentToggleEl.setAttribute("aria-expanded", String(expanded));
    sentArrowEl.textContent = expanded ? "▼" : "▶";
    sentBodyEl.hidden = !expanded;
}

export function toggleCopyHistory() {
    if (!copyHistoryToggleEl) return;
    const expanded = copyHistoryToggleEl.getAttribute("aria-expanded") === "true";
    setCopyHistoryExpanded(!expanded);
}

export function toggleRhythmReview() {
    if (!rhythmReviewToggleEl) return;
    const expanded = rhythmReviewToggleEl.getAttribute("aria-expanded") === "true";
    setRhythmReviewExpanded(!expanded);
}

export function toggleSequence() {
    if (!sequenceToggleEl) return;
    const expanded = sequenceToggleEl.getAttribute("aria-expanded") === "true";
    setSequenceExpanded(!expanded);
}

export function toggleKeyPageActions() {
    if (!keyPageActionsToggleEl) return;
    const expanded = keyPageActionsToggleEl.getAttribute("aria-expanded") === "true";
    setKeyPageActionsExpanded(!expanded);
}

export function toggleSent() {
    if (!sentToggleEl) return;
    const expanded = sentToggleEl.getAttribute("aria-expanded") === "true";
    setSentExpanded(!expanded);
}

export function renderCopyHistoryToggleLabel() {
    const labelEl = document.getElementById("copy-history-label");
    if (!labelEl || !copyHistoryToggleEl) return;
    labelEl.replaceChildren(makeAccelLabel("e", ""));
    copyHistoryToggleEl.title = "Show/hide exercises (E)";
    copyHistoryToggleEl.setAttribute("aria-keyshortcuts", "E");
}

export function renderRhythmReviewToggleLabel() {
    const labelEl = document.getElementById("key-rhythm-review-label");
    if (!labelEl || !rhythmReviewToggleEl) return;
    labelEl.replaceChildren(makeAccelLabel("r", ""));
    rhythmReviewToggleEl.title = "Review rhythm (R)";
    rhythmReviewToggleEl.setAttribute("aria-keyshortcuts", "R");
}

export function renderSequenceToggleLabel() {
    const labelEl = document.getElementById("sequence-toggle-label");
    if (!labelEl || !sequenceToggleEl) return;
    labelEl.replaceChildren(makeAccelLabel("q", ""));
    sequenceToggleEl.title = "Show/hide sequence (Q)";
    sequenceToggleEl.setAttribute("aria-keyshortcuts", "Q");
}

export function renderKeyPageActionsToggleLabel() {
    const labelEl = document.getElementById("key-page-actions-label");
    if (!labelEl || !keyPageActionsToggleEl) return;
    labelEl.replaceChildren(makeAccelLabel("t", ""));
    keyPageActionsToggleEl.title = "Show/hide top menu (T)";
    keyPageActionsToggleEl.setAttribute("aria-keyshortcuts", "T");
}

export function renderSentToggleLabel() {
    const labelEl = document.getElementById("sent-toggle-label");
    if (!labelEl || !sentToggleEl) return;
    // Letters in "Sent" collide with M/S/E/N/T/C/R/Q so the accelerator
    // is bound to an out-of-word X. Render as ``Sent (x)``.
    labelEl.replaceChildren(
        document.createTextNode("Sent ("),
        makeAccelLabel("x", ""),
        document.createTextNode(")"),
    );
    sentToggleEl.title = "Show/hide sent symbols (X)";
    sentToggleEl.setAttribute("aria-keyshortcuts", "X");
}
