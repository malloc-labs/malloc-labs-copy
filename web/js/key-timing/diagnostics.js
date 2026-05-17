// Copy — Key timing page diagnostics.
//
// Two roles:
//
// 1. A rolling buffer of structured event records (`diagnosticEvents`)
//    that the "Copy diagnostics" button serialises to JSONL so the
//    learner can paste a session into a bug report. Capped at
//    MAX_DIAGNOSTIC_EVENTS to keep the buffer bounded.
//
// 2. Live UI inserts: the four single-line readouts (`diag-input`,
//    `diag-event`, `diag-element`, `diag-raw`) and the per-row raw
//    diagnostic log table. Both are rAF-batched — the MIDI handler
//    runs on the same thread as DOM mutations, so per-event row
//    inserts and textContent writes there produce timing jitter that
//    compounds with itself. We queue work synchronously and flush in
//    one animation frame so the main thread stays available for the
//    next MIDI message.
//
// The page controller still owns `keyConfig` and `midiInputArmed`;
// diagnostics reads them through accessors installed at startup.

import { formatTimestamp, kindForNote } from "./utils.js";
import {
    diagElementEl,
    diagEventEl,
    diagInputEl,
    diagRawEl,
    diagRawLogEl,
    keyInputToggleEl,
} from "./dom.js";

const MAX_DIAGNOSTIC_EVENTS = 240;
const MAX_RAW_DIAGNOSTIC_ROWS = 32;
// Wire-protocol tag emitted with every raw-midi diagnostic. Public so
// the page controller can stamp the same constant on its own records
// without diverging from the diagnostic-header.
export const BROWSER_MIDI_INPUT_MODE = "formed-elements";

let diagnosticEvents = [];
let getKeyConfig = () => null;
let getMidiInputArmed = () => true;

export function installDiagnosticsAccessors(accessors) {
    getKeyConfig = accessors.keyConfig;
    getMidiInputArmed = accessors.midiInputArmed;
}

export function focusLabel() {
    const visibility = document.visibilityState;
    const focus = document.hasFocus() ? "focused" : "blurred";
    return `${visibility} / ${focus}`;
}

export function recordDiagnostic(type, details = {}) {
    diagnosticEvents.push({
        at: new Date().toISOString(),
        t_ms: Math.round(performance.now()),
        type,
        focus: focusLabel(),
        ...details,
    });

    while (diagnosticEvents.length > MAX_DIAGNOSTIC_EVENTS) {
        diagnosticEvents.shift();
    }
}

export function diagnosticText() {
    const header = {
        page: location.href,
        copied_at: new Date().toISOString(),
        user_agent: navigator.userAgent,
        visibility: document.visibilityState,
        focused: document.hasFocus(),
        midi_input_armed: getMidiInputArmed(),
        key_config: getKeyConfig(),
        browser_midi_input_mode: BROWSER_MIDI_INPUT_MODE,
    };
    return [
        JSON.stringify({ type: "diagnostic-header", ...header }),
        ...diagnosticEvents.map((event) => JSON.stringify(event)),
    ].join("\n");
}

export function updateInputDiagnostic() {
    const armed = getMidiInputArmed();
    keyInputToggleEl.textContent = armed ? "input armed" : "arm input";
    const current = diagInputEl.textContent || "";
    if (armed && current.includes(" / disarmed")) {
        diagInputEl.textContent = current.replace(" / disarmed", "");
    } else if (!armed && !current.includes("disarmed")) {
        diagInputEl.textContent = `${current || "browser MIDI"} / disarmed`;
    }
}

const pendingRawDiagnosticRows = [];
let pendingDiagRawText = null;
let pendingDiagEventText = null;
let pendingDiagElementText = null;
let diagnosticRenderScheduled = false;

export function scheduleDiagnosticRender() {
    if (diagnosticRenderScheduled) return;
    diagnosticRenderScheduled = true;
    requestAnimationFrame(flushDiagnosticRender);
}

function flushDiagnosticRender() {
    diagnosticRenderScheduled = false;

    if (pendingDiagRawText !== null) {
        diagRawEl.textContent = pendingDiagRawText;
        pendingDiagRawText = null;
    }
    if (pendingDiagEventText !== null) {
        diagEventEl.textContent = pendingDiagEventText;
        pendingDiagEventText = null;
    }
    if (pendingDiagElementText !== null) {
        diagElementEl.textContent = pendingDiagElementText;
        pendingDiagElementText = null;
    }

    if (pendingRawDiagnosticRows.length === 0) return;

    const fragment = document.createDocumentFragment();
    // Newest entry first; queue is in arrival order, so iterate reversed.
    for (let i = pendingRawDiagnosticRows.length - 1; i >= 0; i -= 1) {
        const entry = pendingRawDiagnosticRows[i];
        const row = document.createElement("tr");
        const timestampCell = document.createElement("td");
        const eventCell = document.createElement("td");
        const actionCell = document.createElement("td");
        const focusCell = document.createElement("td");
        timestampCell.textContent = entry.timestamp;
        eventCell.textContent = entry.event;
        actionCell.textContent = entry.action;
        focusCell.textContent = entry.focus;
        row.append(timestampCell, eventCell, actionCell, focusCell);
        fragment.appendChild(row);
    }
    pendingRawDiagnosticRows.length = 0;
    diagRawLogEl.prepend(fragment);
    while (diagRawLogEl.children.length > MAX_RAW_DIAGNOSTIC_ROWS) {
        diagRawLogEl.lastElementChild.remove();
    }
}

export function queueDiagEvent(text) {
    pendingDiagEventText = text;
    scheduleDiagnosticRender();
}

export function queueDiagElement(text) {
    pendingDiagElementText = text;
    scheduleDiagnosticRender();
}

export function appendRawDiagnosticRow(event, action, kind = null) {
    const resolvedKind = kind || kindForNote(event.note, getKeyConfig()) || "unknown";
    const state = event.pressed ? "down" : "up";
    pendingDiagRawText = `${resolvedKind} ${state} / note ${event.note} / ${action}`;
    pendingRawDiagnosticRows.push({
        timestamp: formatTimestamp(),
        event: `${resolvedKind} ${state} / note ${event.note}`,
        action,
        focus: focusLabel(),
    });
    scheduleDiagnosticRender();
}

