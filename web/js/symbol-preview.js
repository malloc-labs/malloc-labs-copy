// Shared Left-Alt symbol preview helpers.
//
// Pages own their audio/session gating, but the keycode mapping and
// centered Morse disclosure are common anywhere the Koch sequence row
// appears.

import { PATTERNS, spokenMorsePattern } from "./morse-display.js";

const PREVIEW_CODE_TO_SYMBOL = (() => {
    const map = new Map();
    for (let i = 0; i < 26; i++) {
        map.set(`Key${String.fromCharCode(65 + i)}`, String.fromCharCode(65 + i));
    }
    for (let i = 0; i <= 9; i++) {
        map.set(`Digit${i}`, String(i));
    }
    map.set("Period", ".");
    map.set("Comma", ",");
    map.set("Equal", "=");
    return map;
})();

let popupEl = null;
let hideTimer = null;
const FALLBACK_HIDE_MS = 10_000;

export function symbolForPreviewCode(code, shiftKey) {
    if (code === "Slash") return shiftKey ? "?" : "/";
    return PREVIEW_CODE_TO_SYMBOL.get(code) || null;
}

export function showSymbolPreview(symbol) {
    const pattern = PATTERNS[symbol];
    if (!pattern) return;

    if (!popupEl) {
        popupEl = document.createElement("div");
        popupEl.className = "symbol-preview-popup";
        popupEl.setAttribute("role", "status");
        popupEl.setAttribute("aria-live", "polite");
        document.body.appendChild(popupEl);
    }

    const spoken = spokenMorsePattern(pattern);
    popupEl.innerHTML = `
        <div class="symbol-preview-popup__symbol">${symbol}</div>
        <div class="symbol-preview-popup__spoken">${spoken}</div>
    `;
    popupEl.setAttribute("aria-label", `${symbol}: ${spoken}`);
    popupEl.dataset.visible = "true";

    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(hideSymbolPreview, FALLBACK_HIDE_MS);
}

export function hideSymbolPreview() {
    if (!popupEl) return;
    if (hideTimer) {
        clearTimeout(hideTimer);
        hideTimer = null;
    }
    delete popupEl.dataset.visible;
}
