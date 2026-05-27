// Copy — Key timing page Koch sequence row.
//
// Renders the 41-symbol Koch row at the top of the page: each token is
// claimed / next / available on Cadence, or uniformly available on
// Freeplay (which lets every symbol preview-play regardless of the
// curriculum gate). The "playing" pulse is set by the morse-repeat-
// start/end events from the engine.
//
// Owns the claimedSymbolSet so the preview keydown handler in the page
// controller can ask claimedSymbolHas(symbol) without reaching into
// module-internal state.

import { copyHistoryEl, sequenceRow } from "./dom.js";
import { KOCH_ORDER } from "../partials/koch-sequence.js";

let claimedSymbolSet = new Set();

export function claimedSymbolHas(symbol) {
    return claimedSymbolSet.has(symbol);
}

export function setSequenceTokenPlaying(symbol, playing) {
    sequenceRow.querySelectorAll("[data-playing]").forEach((el) => {
        delete el.dataset.playing;
    });
    if (!playing || !symbol) return;
    const token = sequenceRow.querySelector(`[data-symbol="${CSS.escape(symbol)}"]`);
    if (token) token.dataset.playing = "true";
}

export function renderSequence(state) {
    const claimedSet = new Set(state.symbols);
    claimedSymbolSet = claimedSet;
    const next = state.suggested_next;
    // Freeplay and Copy Key render every token uniformly — no "next"
    // highlight, no send-side nudge. Copy Key is a combined exercise
    // of two disciplines, not a progression zone.
    const isCopyKey = !!document.querySelector(".copy-key-shell");
    const uniform = !copyHistoryEl || isCopyKey;
    if (!isCopyKey) {
        sequenceRow.dataset.ready = state.ready_for_next_send ? "true" : "false";
    }

    KOCH_ORDER.forEach((sym) => {
        const token = sequenceRow.querySelector(`[data-symbol="${CSS.escape(sym)}"]`);
        if (!token) return;

        if (uniform) {
            token.dataset.state = claimedSet.has(sym) ? "claimed" : "available";
            token.title = claimedSet.has(sym) ? `${sym} — known` : `${sym} — not yet known`;
        } else if (claimedSet.has(sym)) {
            token.dataset.state = "claimed";
            token.title = `${sym} — known`;
        } else if (sym === next) {
            token.dataset.state = "next";
            token.title = `${sym} — next in sequence`;
        } else {
            token.dataset.state = "available";
            token.title = `${sym} — not yet known`;
        }
    });
}
