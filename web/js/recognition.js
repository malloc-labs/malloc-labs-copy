// Copy — Symbol Recognition UI.
//
// Connects to the engine to read the claimed symbol set and render
// the Koch sequence row with nudge state. No session logic yet —
// this is the training counterpart to Koch Exercises (practice).

import {
    connectKoch,
    installClaimHandlers,
    renderSequence,
    setSequenceTokenPlaying,
} from "./koch-core.js";

const sequenceRow  = document.getElementById("sequence-row");
const primedTextEl = document.getElementById("primed-text");

let socket = null;
let claimedState = { symbols: [], suggested_next: null, set_is_fresh: true };

function renderPrimed() {
    if (!claimedState.symbols.length) {
        primedTextEl.textContent = "Primed: nothing — claim a symbol first";
        return;
    }
    primedTextEl.textContent =
        `Recognition: ${claimedState.symbols.join(", ")}`;
}

socket = connectKoch({
    onMessage(event) {
        if (event.type === "claimed-symbols") {
            claimedState = event;
            renderSequence(sequenceRow, event);
            renderPrimed();
        }
        if (event.type === "morse-repeat-start") {
            setSequenceTokenPlaying(sequenceRow, event.symbol, true);
        }
        if (event.type === "morse-repeat-end") {
            setSequenceTokenPlaying(sequenceRow, event.symbol, false);
        }
    },
});

installClaimHandlers(sequenceRow, () => socket);
