// Copy - Settings page.
//
// This page writes the shared [audio] timing keys used by every listening
// environment. User-facing labels follow established Morse learning terms:
// character speed = symbol cadence, effective speed = pressure after spacing.

import { getDeveloperModeEnabled, setDeveloperModeEnabled } from "./developer-mode.js";
import { setHHClearEnabled } from "./hh-clear.js";
import {
    TRINKEY_SYNC_RESULT,
    sendTrinkeySync,
} from "./key-timing/trinkey-sync.js";
import { getObservedDit, subscribeObservedDit } from "./trinkey-observed.js";

const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
const wsUrl = `${wsProtocol}//${location.host}/ws`;
const form = document.getElementById("audio-settings-form");
const characterInput = document.getElementById("character-wpm");
const effectiveInput = document.getElementById("effective-wpm");
const signalStrengthInput = document.getElementById("signal-strength");
const signalToneInput = document.getElementById("signal-tone");
const cadenceVariationInput = document.getElementById("cadence-variation");
const rstTableBody = document.getElementById("rst-table-body");
const keyerModeRadios = document.querySelectorAll('input[name="keyer_mode"]');
const keyerModeSyncButton = document.getElementById("keyer-mode-sync");
const keyerModeSyncStatusEl = document.getElementById("keyer-mode-sync-status");
const observedDitReadoutEl = document.getElementById("observed-dit-readout");
const saveDirectoryInput = document.getElementById("save-directory");
const warmUpTimeoutInput = document.getElementById("warm-up-timeout");
const saveButton = document.getElementById("save-audio-settings");
const playTestButton = document.getElementById("play-test-message");
const saveTestButton = document.getElementById("save-test-message");
const statusEl = document.getElementById("settings-status");
const characterSummary = document.getElementById("character-speed-summary");
const effectiveSummary = document.getElementById("effective-speed-summary");
const developerModeInput = document.getElementById("developer-mode");
const hhClearInput = document.getElementById("hh-clear-enabled");

developerModeInput.checked = getDeveloperModeEnabled();
developerModeInput.addEventListener("change", () => {
    setDeveloperModeEnabled(developerModeInput.checked);
});

let socket = null;
let isSaving = false;
let savedSettings = null;
let isPlayingTestMessage = false;
let isSavingTestMessage = false;
let wavExport = null;

function setStatus(status, text) {
    statusEl.dataset.status = status;
    statusEl.textContent = text;
}

// Backend stores receiver_bed and tone_shape as 0-10; UI exposes the
// standard RST scale (1-9) for Strength and Tone. Mapping is linear and
// rounded; S is inverted because a higher bed level means a quieter
// signal-to-noise ratio. The 11→9 collapse is lossy at the seams (e.g.
// bed=3 ↔ S7 ↔ bed=2 on roundtrip), so backendPayload() preserves the
// loaded backend value when the user has not visibly changed the input.
function sFromBed(bed) {
    return Math.max(1, Math.min(9, Math.round(9 - (8 * bed) / 10)));
}
function bedFromS(s) {
    return Math.max(0, Math.min(10, Math.round(((9 - s) * 10) / 8)));
}
function tFromToneShape(toneShape) {
    return Math.max(1, Math.min(9, Math.round(1 + (8 * toneShape) / 10)));
}
function toneShapeFromT(t) {
    return Math.max(0, Math.min(10, Math.round(((t - 1) * 10) / 8)));
}

function updateRstMarker() {
    if (!rstTableBody) return;
    const s = Number(signalStrengthInput.value);
    const t = Number(signalToneInput.value);
    for (const row of rstTableBody.querySelectorAll("tr")) {
        const n = Number(row.dataset.row);
        row.dataset.markS = n === s ? "true" : "false";
        row.dataset.markT = n === t ? "true" : "false";
    }
}

function setInputsEnabled(enabled) {
    characterInput.disabled = !enabled;
    effectiveInput.disabled = !enabled;
    signalStrengthInput.disabled = !enabled;
    signalToneInput.disabled = !enabled;
    cadenceVariationInput.disabled = !enabled;
    keyerModeRadios.forEach((radio) => { radio.disabled = !enabled; });
    keyerModeSyncButton.disabled = !enabled;
    saveDirectoryInput.disabled = !enabled;
    warmUpTimeoutInput.disabled = !enabled;
    hhClearInput.disabled = !enabled;
    playTestButton.disabled = !enabled;
    saveTestButton.disabled = !enabled;
}

function getKeyerMode() {
    const checked = Array.from(keyerModeRadios).find((radio) => radio.checked);
    return checked?.value || "iambic_a";
}

function setKeyerModeSyncStatus(text) {
    keyerModeSyncStatusEl.textContent = text;
}

function describeSyncResult(outcome) {
    switch (outcome.result) {
        case TRINKEY_SYNC_RESULT.SENT: {
            const parts = [];
            if (outcome.sent?.mode) parts.push(`PC ${outcome.program_number}`);
            if (outcome.sent?.wpm) parts.push(`CC1 ${outcome.cc1_value}`);
            const payload = parts.length ? parts.join(" + ") : "nothing";
            return `sent ${payload} to ${outcome.output_name || "Trinkey"}`;
        }
        case TRINKEY_SYNC_RESULT.UNKNOWN_MODE:
            return `unknown mode "${outcome.mode}"`;
        case TRINKEY_SYNC_RESULT.MIDI_UNAVAILABLE:
            return "browser does not support MIDI";
        case TRINKEY_SYNC_RESULT.MIDI_BLOCKED:
            return outcome.detail ? `MIDI blocked: ${outcome.detail}` : "MIDI access denied";
        case TRINKEY_SYNC_RESULT.NO_OUTPUT:
            return "no Trinkey output found";
        case TRINKEY_SYNC_RESULT.SEND_FAILED:
            return outcome.detail ? `send failed: ${outcome.detail}` : "send failed";
        default:
            return "unknown result";
    }
}

function currentSettings() {
    const character = Number(characterInput.value);
    const effective = Number(effectiveInput.value);
    const s = Number(signalStrengthInput.value);
    const t = Number(signalToneInput.value);
    const cadenceVariation = Number(cadenceVariationInput.value);
    const keyerMode = getKeyerMode();
    const hhClearEnabled = hhClearInput.checked;
    const saveDirectory = saveDirectoryInput.value.trim();
    const warmUpTimeout = Number(warmUpTimeoutInput.value);
    return {
        character,
        effective,
        s,
        t,
        cadenceVariation,
        keyerMode,
        hhClearEnabled,
        saveDirectory,
        warmUpTimeout,
    };
}

function backendPayload() {
    const { character, effective, s, t, cadenceVariation, keyerMode, hhClearEnabled, saveDirectory, warmUpTimeout } =
        currentSettings();
    const receiverBed = savedSettings && s === savedSettings.s
        ? savedSettings.bed
        : bedFromS(s);
    const toneShape = savedSettings && t === savedSettings.t
        ? savedSettings.toneShape
        : toneShapeFromT(t);
    return {
        character_wpm: character,
        effective_wpm: effective,
        tone_shape: toneShape,
        receiver_bed: receiverBed,
        cadence_variation: cadenceVariation,
        keyer_mode: keyerMode,
        hh_clear_enabled: hhClearEnabled,
        save_directory: saveDirectory,
        warm_up_timeout_minutes: warmUpTimeout,
    };
}

function updateSummaries() {
    const { character, effective } = currentSettings();
    characterSummary.textContent =
        Number.isFinite(character) && character > 0 ? `${character} WPM` : "Character WPM";
    effectiveSummary.textContent =
        Number.isFinite(effective) && effective > 0 ? `${effective} WPM` : "Effective WPM";
}

function validateSettings() {
    const { character, effective, s, t, cadenceVariation, saveDirectory, warmUpTimeout } = currentSettings();
    if (!Number.isInteger(character) || character <= 0) {
        return "Character speed must be a positive whole number.";
    }
    if (!Number.isInteger(effective) || effective <= 0) {
        return "Effective speed must be a positive whole number.";
    }
    if (effective > character) {
        return "Effective speed cannot exceed character speed.";
    }
    if (!Number.isInteger(s) || s < 1 || s > 9) {
        return "Strength (S) must be between 1 and 9.";
    }
    if (!Number.isInteger(t) || t < 1 || t > 9) {
        return "Tone (T) must be between 1 and 9.";
    }
    if (!Number.isInteger(cadenceVariation) || cadenceVariation < 0 || cadenceVariation > 5) {
        return "Cadence Variation must be between 0 and 5.";
    }
    if (!saveDirectory) {
        return "Save Directory must not be empty.";
    }
    if (!Number.isInteger(warmUpTimeout) || warmUpTimeout < 1) {
        return "Warm-up timeout must be a positive whole number of minutes.";
    }
    return "";
}

const DIRTY_FIELDS = [
    "character",
    "effective",
    "s",
    "t",
    "cadenceVariation",
    "keyerMode",
    "hhClearEnabled",
    "saveDirectory",
    "warmUpTimeout",
];

function isDirty() {
    if (!savedSettings) return false;
    const current = currentSettings();
    return DIRTY_FIELDS.some((key) => current[key] !== savedSettings[key]);
}

function updateSaveState() {
    const validationError = validateSettings();
    const dirty = isDirty();
    saveButton.classList.remove("btn--primary");

    if (isSaving) {
        saveButton.disabled = true;
        saveButton.textContent = "Saving";
    } else if (validationError) {
        saveButton.disabled = true;
        saveButton.textContent = dirty ? "Save Settings" : "Saved";
    } else if (dirty) {
        saveButton.disabled = false;
        saveButton.classList.add("btn--primary");
        saveButton.textContent = "Save Settings";
    } else {
        saveButton.disabled = true;
        saveButton.textContent = "Saved";
    }

    updateTestMessageState(validationError);
    return { validationError, dirty };
}

function updateTestMessageState(validationError = validateSettings()) {
    const ready = !validationError && socket && socket.readyState === WebSocket.OPEN;
    playTestButton.disabled = !ready || isSaving || isPlayingTestMessage || isSavingTestMessage;
    playTestButton.textContent = isPlayingTestMessage ? "Playing" : "Play";
    saveTestButton.disabled = !ready || isSaving || isSavingTestMessage || isPlayingTestMessage;
    saveTestButton.textContent = isSavingTestMessage ? "Saving WAV" : "Save WAV";
}

function saveBase64Wav(chunks, filename) {
    const binary = atob(chunks.join(""));
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i);
    }

    const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
}

function renderAudioSettings(event) {
    characterInput.value = event.character_wpm;
    effectiveInput.value = event.effective_wpm;
    const s = sFromBed(event.receiver_bed);
    const t = tFromToneShape(event.tone_shape);
    signalStrengthInput.value = s;
    signalToneInput.value = t;
    cadenceVariationInput.value = event.cadence_variation;
    const incomingKeyerMode = typeof event.keyer_mode === "string" ? event.keyer_mode : "iambic_a";
    keyerModeRadios.forEach((radio) => {
        radio.checked = radio.value === incomingKeyerMode;
    });
    hhClearInput.checked = Boolean(event.hh_clear_enabled);
    saveDirectoryInput.value = event.save_directory || "";
    warmUpTimeoutInput.value = event.warm_up_timeout_minutes || 10;
    // Keep the localStorage cache that Key pages read in sync with the
    // authoritative server state.
    setHHClearEnabled(Boolean(event.hh_clear_enabled));
    const previousKeyerMode = savedSettings?.keyerMode || null;
    const previousCharacterWpm = savedSettings ? savedSettings.character : null;
    savedSettings = {
        character: event.character_wpm,
        effective: event.effective_wpm,
        s,
        t,
        bed: event.receiver_bed,
        toneShape: event.tone_shape,
        cadenceVariation: event.cadence_variation,
        keyerMode: incomingKeyerMode,
        hhClearEnabled: Boolean(event.hh_clear_enabled),
        saveDirectory: event.save_directory || "",
        warmUpTimeout: event.warm_up_timeout_minutes || 10,
    };
    updateSummaries();
    updateRstMarker();
    const prefix = isSaving ? "saved" : "ready";
    const justSaved = isSaving;
    isSaving = false;
    if (justSaved) {
        const modeChanged = previousKeyerMode && previousKeyerMode !== incomingKeyerMode;
        const wpmChanged = previousCharacterWpm != null
            && previousCharacterWpm !== event.character_wpm;
        if (modeChanged || wpmChanged) {
            // Mode and/or WPM changed on this save round-trip — push the
            // affected values to the firmware so the Trinkey stays in
            // step with Copy's configured intent.
            syncTrinkey({
                mode: modeChanged ? incomingKeyerMode : null,
                wpm: wpmChanged ? event.character_wpm : null,
            });
        }
    }
    setStatus(
        "connected",
        `${prefix} - ${event.character_wpm} WPM characters / ${event.effective_wpm} WPM effective`
    );
    setInputsEnabled(true);
    updateSaveState();
    // savedSettings.character just changed → refresh drift comparison.
    renderObservedDit();
}

function connect() {
    setInputsEnabled(false);
    updateSaveState();
    setStatus("connecting", "connecting");
    socket = new WebSocket(wsUrl);

    socket.addEventListener("open", () => {
        setStatus("connected", "loading");
        socket.send(JSON.stringify({ action: "get-audio-settings" }));
    });

    socket.addEventListener("message", (msg) => {
        let event;
        try {
            event = JSON.parse(msg.data);
        } catch {
            return;
        }

        if (event.type === "audio-settings") {
            renderAudioSettings(event);
        } else if (event.type === "error" && event.reason === "invalid-audio-settings") {
            isSaving = false;
            setStatus("error", event.detail || "invalid settings");
            setInputsEnabled(true);
            updateSaveState();
        } else if (event.type === "test-message-start") {
            isPlayingTestMessage = true;
            setStatus("connected", "playing test message");
            updateTestMessageState();
        } else if (event.type === "test-message-end") {
            isPlayingTestMessage = false;
            setStatus("connected", "test message complete");
            updateTestMessageState();
        } else if (event.type === "test-message-wav-start") {
            wavExport = { filename: event.filename, chunks: [] };
            isSavingTestMessage = true;
            setStatus("connected", "saving WAV");
            updateTestMessageState();
        } else if (event.type === "test-message-wav-chunk" && wavExport) {
            wavExport.chunks.push(event.data);
        } else if (event.type === "test-message-wav-end" && wavExport) {
            saveBase64Wav(wavExport.chunks, event.filename || wavExport.filename);
            wavExport = null;
            isSavingTestMessage = false;
            setStatus("connected", "WAV saved");
            updateTestMessageState();
        } else if (
            event.type === "error" &&
            (event.reason === "invalid-test-message-settings" ||
                event.reason === "test-message-playback-failed")
        ) {
            isPlayingTestMessage = false;
            isSavingTestMessage = false;
            wavExport = null;
            setStatus("error", event.detail || "test message failed");
            updateTestMessageState();
        }
    });

    socket.addEventListener("close", () => {
        isSaving = false;
        isPlayingTestMessage = false;
        isSavingTestMessage = false;
        wavExport = null;
        setInputsEnabled(false);
        saveButton.disabled = true;
        playTestButton.disabled = true;
        saveButton.classList.remove("btn--primary");
        setStatus("disconnected", "disconnected");
    });

    socket.addEventListener("error", () => {
        isSaving = false;
        isPlayingTestMessage = false;
        isSavingTestMessage = false;
        setStatus("error", "connection error");
        updateTestMessageState();
    });
}

form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!socket || socket.readyState !== WebSocket.OPEN) return;

    const validationError = validateSettings();
    if (validationError) {
        setStatus("error", validationError);
        return;
    }
    if (!isDirty()) return;

    setInputsEnabled(false);
    isSaving = true;
    updateSaveState();
    setStatus("connected", "saving");
    socket.send(
        JSON.stringify({
            action: "set-audio-settings",
            ...backendPayload(),
        })
    );
});

async function syncTrinkey({ mode = null, wpm = null } = {}) {
    if (mode == null && wpm == null) return;
    setKeyerModeSyncStatus("sending");
    const outcome = await sendTrinkeySync({ mode, wpm });
    setKeyerModeSyncStatus(describeSyncResult(outcome));
}

keyerModeSyncButton.addEventListener("click", () => {
    const mode = savedSettings?.keyerMode || getKeyerMode();
    const wpm = savedSettings?.character
        ?? (Number.isFinite(Number(characterInput.value)) ? Number(characterInput.value) : null);
    syncTrinkey({ mode, wpm });
});

function testMessagePayload() {
    const {
        character_wpm,
        effective_wpm,
        tone_shape,
        receiver_bed,
        cadence_variation,
    } = backendPayload();
    return {
        character_wpm,
        effective_wpm,
        tone_shape,
        receiver_bed,
        cadence_variation,
    };
}

playTestButton.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;

    const validationError = validateSettings();
    if (validationError) {
        setStatus("error", validationError);
        updateTestMessageState(validationError);
        return;
    }

    socket.send(JSON.stringify({ action: "play-test-message", ...testMessagePayload() }));
});

saveTestButton.addEventListener("click", () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;

    const validationError = validateSettings();
    if (validationError) {
        setStatus("error", validationError);
        updateTestMessageState(validationError);
        return;
    }

    isSavingTestMessage = true;
    wavExport = null;
    setStatus("connected", "saving WAV");
    updateTestMessageState();
    socket.send(JSON.stringify({ action: "save-test-message", ...testMessagePayload() }));
});

function onSettingsInput() {
    updateSummaries();
    updateRstMarker();
    if (!savedSettings) return;

    const { validationError, dirty } = updateSaveState();
    if (validationError) {
        setStatus("error", validationError);
    } else if (dirty) {
        setStatus("connected", "unsaved changes");
    } else {
        setStatus(
            "connected",
            `ready - ${savedSettings.character} WPM characters / ${savedSettings.effective} WPM effective`
        );
    }
}

[
    characterInput,
    effectiveInput,
    signalStrengthInput,
    signalToneInput,
    cadenceVariationInput,
    saveDirectoryInput,
    warmUpTimeoutInput,
].forEach((input) => input.addEventListener("input", onSettingsInput));

keyerModeRadios.forEach((radio) => radio.addEventListener("change", onSettingsInput));
hhClearInput.addEventListener("change", onSettingsInput);

// Within ±5% of the configured dit duration counts as a match; outside
// that band we flag drift so the learner can either re-sync (Path A) or
// adjust Copy's WPM to match what the device is doing (Path B).
const DRIFT_TOLERANCE = 0.05;
// Stale after one hour — older than that and the readout is more
// likely a record of an old session than the device's current state.
const OBSERVED_STALE_MS = 60 * 60 * 1000;

function formatObservedAge(ageMs) {
    const seconds = Math.round(ageMs / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.round(seconds / 60);
    return `${minutes}m ago`;
}

function renderObservedDit() {
    const snapshot = getObservedDit();
    if (!snapshot) {
        observedDitReadoutEl.dataset.state = "idle";
        observedDitReadoutEl.textContent = "no recent keying";
        return;
    }

    const ageMs = Date.now() - snapshot.observedAt;
    if (ageMs > OBSERVED_STALE_MS) {
        observedDitReadoutEl.dataset.state = "idle";
        observedDitReadoutEl.textContent = `no recent keying (last seen ${formatObservedAge(ageMs)})`;
        return;
    }

    const configuredWpm = savedSettings?.character;
    const ditMs = Math.round(snapshot.ditMs * 10) / 10;
    const wpm = Math.round(snapshot.wpm * 10) / 10;
    const base = `~${ditMs} ms dit (${wpm} WPM), measured ${formatObservedAge(ageMs)}`;

    if (!Number.isFinite(configuredWpm) || configuredWpm <= 0) {
        observedDitReadoutEl.dataset.state = "match";
        observedDitReadoutEl.textContent = base;
        return;
    }

    const expectedDitMs = 1200 / configuredWpm;
    const drift = Math.abs(snapshot.ditMs - expectedDitMs) / expectedDitMs;
    if (drift <= DRIFT_TOLERANCE) {
        observedDitReadoutEl.dataset.state = "match";
        observedDitReadoutEl.textContent = `${base} — matches configured ${configuredWpm} WPM`;
    } else {
        observedDitReadoutEl.dataset.state = "drift";
        observedDitReadoutEl.textContent = `${base} — does not match configured ${configuredWpm} WPM (Sync now, or change WPM to match)`;
    }
}

subscribeObservedDit(renderObservedDit);
renderObservedDit();

connect();
