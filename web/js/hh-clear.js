// Copy — "HH clears the send area" developer easter egg.
//
// When the toggle is on (see Settings → Developer), keying two H's in a row
// triggers the same clear that the "clear" button does. The toggle state is
// persisted in localStorage; the detector keeps the last-seen symbol in
// memory and surfaces a callback when the HH pair lands.
//
// The toggle is dev-only — the rest of the project should not assume HH is
// reserved. The Python exercise generator does still produce HH substrings;
// see the TODO in copy_653/sequence/copy_exercises.py.

const STORAGE_KEY = "copy-653:hh-clear-enabled";

export function getHHClearEnabled() {
    try {
        return window.localStorage?.getItem(STORAGE_KEY) === "true";
    } catch (_) {
        return false;
    }
}

export function setHHClearEnabled(enabled) {
    try {
        window.localStorage?.setItem(STORAGE_KEY, enabled ? "true" : "false");
    } catch (_) {
        /* localStorage unavailable */
    }
}

let lastSent = null;

// Call on every sent-symbol event. ``leadingGap`` is the server's
// classification of the silence preceding this symbol — "none" |
// "character" | "word". The trigger only fires when the two H's belong
// to the same word (character-gap); H followed by a word gap and then
// H reads as "H H", not "HH", and is left alone.
export function noteSentSymbol(symbol, leadingGap, onTrigger) {
    if (!getHHClearEnabled()) {
        lastSent = symbol;
        return;
    }
    if (lastSent === "H" && symbol === "H" && leadingGap === "character") {
        lastSent = null;
        if (typeof onTrigger === "function") onTrigger();
        return;
    }
    lastSent = symbol;
}

export function resetHHClearTracker() {
    lastSent = null;
}
