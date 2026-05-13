// Copy — Developer mode.
//
// When enabled, elements marked `.developer-only` become visible. The flag is
// persisted in localStorage and synced across tabs via the storage event so a
// toggle on the Settings page reveals diagnostic UI on other open pages.

const STORAGE_KEY = "copy-653:developer-mode-enabled";

export function getDeveloperModeEnabled() {
    try {
        return window.localStorage?.getItem(STORAGE_KEY) === "true";
    } catch (_) {
        return false;
    }
}

export function setDeveloperModeEnabled(enabled) {
    try {
        window.localStorage?.setItem(STORAGE_KEY, enabled ? "true" : "false");
    } catch (_) { /* localStorage unavailable */ }
    applyDeveloperModeClass();
}

function applyDeveloperModeClass() {
    document.body.classList.toggle("developer-mode", getDeveloperModeEnabled());
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyDeveloperModeClass);
} else {
    applyDeveloperModeClass();
}

window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY) applyDeveloperModeClass();
});
