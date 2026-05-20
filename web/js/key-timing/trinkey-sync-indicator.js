// Compact sync-status indicator in the Key page header.
//
// Reads the last-known observed dit duration from localStorage on
// init, listens for key-input-start to capture the configured WPM,
// and subscribes to observed-dit updates so the dot tracks drift as
// the learner keys. Clicking it just navigates to Settings — Sync now
// stays a deliberate action there, not a one-misclick affair.
//
// Three states (data-state attribute):
//   idle    — no recent observation, or observation older than the
//             staleness window. Tooltip: "no recent keying".
//   match   — observed dit within ±5% of expected. Tooltip names both.
//   drift   — observed dit outside the tolerance. Tooltip names both
//             and hints at the remedy.

import { getObservedDit, subscribeObservedDit } from "../trinkey-observed.js";

const DRIFT_TOLERANCE = 0.05;
const OBSERVED_STALE_MS = 60 * 60 * 1000;

let indicatorEl = null;
let configuredWpm = null;

function formatAge(ageMs) {
    const seconds = Math.round(ageMs / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.round(seconds / 60);
    return `${minutes}m ago`;
}

function render() {
    if (!indicatorEl) return;
    const snapshot = getObservedDit();
    if (!snapshot) {
        indicatorEl.dataset.state = "idle";
        indicatorEl.title = "no recent keying — click to open Settings";
        return;
    }
    const ageMs = Date.now() - snapshot.observedAt;
    if (ageMs > OBSERVED_STALE_MS) {
        indicatorEl.dataset.state = "idle";
        indicatorEl.title = `last observed ${formatAge(ageMs)} — click to open Settings`;
        return;
    }

    const observedWpm = Math.round(snapshot.wpm * 10) / 10;
    if (!Number.isFinite(configuredWpm) || configuredWpm <= 0) {
        indicatorEl.dataset.state = "match";
        indicatorEl.title = `Trinkey emitting ${observedWpm} WPM (${formatAge(ageMs)})`;
        return;
    }

    const expectedDitMs = 1200 / configuredWpm;
    const drift = Math.abs(snapshot.ditMs - expectedDitMs) / expectedDitMs;
    if (drift <= DRIFT_TOLERANCE) {
        indicatorEl.dataset.state = "match";
        indicatorEl.title = `Trinkey emitting ${observedWpm} WPM, matches configured ${configuredWpm} WPM (${formatAge(ageMs)})`;
    } else {
        indicatorEl.dataset.state = "drift";
        indicatorEl.title = `Trinkey emitting ${observedWpm} WPM, configured ${configuredWpm} WPM — click to open Settings and Sync now`;
    }
}

export function initTrinkeySyncIndicator() {
    indicatorEl = document.getElementById("trinkey-sync-indicator");
    if (!indicatorEl) return;

    document.addEventListener("copy-653:key-input-start", (event) => {
        const wpm = Number(event.detail?.characterWpm);
        if (Number.isFinite(wpm) && wpm > 0) {
            configuredWpm = wpm;
            render();
        }
    });

    subscribeObservedDit(render);
    render();
}
