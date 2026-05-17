// Copy — Key timing page utilities.
//
// Pure helpers shared across the key-timing modules. No DOM queries,
// no module-level state — anything that needs page state lives in the
// owning module.

export function formatMs(value) {
    if (!Number.isFinite(value)) return "—";
    return `${Math.round(value)} ms`;
}

export function formatRatio(value) {
    if (!Number.isFinite(value)) return "—";
    return `${value.toFixed(2)} dits`;
}

export function formatTimestamp(date = new Date()) {
    const time = date.toLocaleTimeString([], { hour12: false });
    const milliseconds = date.getMilliseconds().toString().padStart(3, "0");
    return `${time}.${milliseconds}`;
}

export function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
}

// Build an accelerator label of the form "<u>X</u>rest" — used by every
// shortcut-bearing button on the key page. Returns a DocumentFragment.
export function makeAccelLabel(accel, rest) {
    const u = document.createElement("u");
    u.textContent = accel;
    const fragment = document.createDocumentFragment();
    fragment.append(u, document.createTextNode(rest));
    return fragment;
}
