// Copy — Key timing page DOM references.
//
// Single source of truth for the page elements the key-timing modules
// read or mutate. Some IDs are Cadence-only and absent on the Freeplay
// page; consumers must null-check those (the comments below mark them).

export const statusEl = document.querySelector(".status");
export const sequenceRow = document.getElementById("sequence-row");
export const sentSymbolEl = document.getElementById("sent-symbol");
export const sentHistoryEl = document.getElementById("sent-history");
export const rhythmReviewToggleEl = document.getElementById("key-rhythm-review-toggle");
export const rhythmReviewArrowEl = document.getElementById("key-rhythm-review-arrow");
export const rhythmReviewMetaEl = document.getElementById("key-rhythm-review-meta");
export const rhythmReviewBodyEl = document.getElementById("key-rhythm-review-body");
export const rhythmReviewSymbolsEl = document.getElementById("key-rhythm-review-symbols");
export const rhythmReviewTabsEl = document.getElementById("key-rhythm-review-tabs");
export const soundToggleEl = document.getElementById("key-sound-toggle");
export const clearSentEl = document.getElementById("key-clear-sent");
export const newSetEl = document.getElementById("key-new-set");
export const keyInputToggleEl = document.getElementById("key-input-toggle");
export const copyDiagnosticsEl = document.getElementById("copy-diagnostics");
export const diagInputEl = document.getElementById("diag-input");
export const diagAudioEl = document.getElementById("diag-audio");
export const diagEventEl = document.getElementById("diag-event");
export const diagRawEl = document.getElementById("diag-raw");
export const diagElementEl = document.getElementById("diag-element");
export const diagGapEl = document.getElementById("diag-gap");
export const diagTimingEl = document.getElementById("diag-timing");
export const diagLogEl = document.getElementById("diag-log");
export const diagRawLogEl = document.getElementById("diag-raw-log");
// Copy section is Cadence-only; absent on the Freeplay page.
export const copySymbolEl = document.getElementById("copy-symbol");
export const copyImiEl = document.getElementById("copy-imi");
export const copyHistoryEl = document.getElementById("copy-history");
export const copyPositionLabelEl = document.getElementById("copy-position-label");
export const copyHistoryToggleEl = document.getElementById("copy-history-toggle");
export const copyHistoryArrowEl = document.getElementById("copy-history-arrow");
// Cadence-only collapsible toggles. Absent on the Freeplay page —
// every reference below must guard for null.
export const sequenceToggleEl = document.getElementById("sequence-toggle");
export const sequenceArrowEl = document.getElementById("sequence-arrow");
export const keyPageActionsToggleEl = document.getElementById("key-page-actions-toggle");
export const keyPageActionsArrowEl = document.getElementById("key-page-actions-arrow");
export const keyPageActionsItemsEl = document.getElementById("key-page-actions-items");
export const sentToggleEl = document.getElementById("sent-toggle");
export const sentArrowEl = document.getElementById("sent-arrow");
export const sentBodyEl = document.getElementById("key-sent-body");
export const cadenceSpeakerEl = document.getElementById("cadence-speaker");
