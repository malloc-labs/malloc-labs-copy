// Copy - Settings page.
//
// This page writes the shared [audio] timing keys used by every listening
// environment. User-facing labels follow established Morse learning terms:
// character speed = symbol cadence, effective speed = pressure after spacing.

import { getDeveloperModeEnabled, setDeveloperModeEnabled } from "./developer-mode.js";

const RUNAWAY_GUARD_STORAGE_KEY = "copy-653:runaway-guard-enabled";

const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
const wsUrl = `${wsProtocol}//${location.host}/ws`;
const form = document.getElementById("audio-settings-form");
const characterInput = document.getElementById("character-wpm");
const effectiveInput = document.getElementById("effective-wpm");
const toneShapeInput = document.getElementById("tone-shape");
const receiverBedInput = document.getElementById("receiver-bed");
const cadenceVariationInput = document.getElementById("cadence-variation");
const trinkeyBuzzerInput = document.getElementById("trinkey-buzzer");
const saveButton = document.getElementById("save-audio-settings");
const playTestButton = document.getElementById("play-test-message");
const saveTestButton = document.getElementById("save-test-message");
const statusEl = document.getElementById("settings-status");
const characterSummary = document.getElementById("character-speed-summary");
const effectiveSummary = document.getElementById("effective-speed-summary");
const developerModeInput = document.getElementById("developer-mode");
const runawayGuardInput = document.getElementById("runaway-guard-enabled");

developerModeInput.checked = getDeveloperModeEnabled();
developerModeInput.addEventListener("change", () => {
    setDeveloperModeEnabled(developerModeInput.checked);
});

function isRunawayGuardEnabled() {
    try {
        return window.localStorage?.getItem(RUNAWAY_GUARD_STORAGE_KEY) !== "false";
    } catch (_) {
        return true;
    }
}

runawayGuardInput.checked = isRunawayGuardEnabled();
runawayGuardInput.addEventListener("change", () => {
    try {
        window.localStorage?.setItem(
            RUNAWAY_GUARD_STORAGE_KEY,
            runawayGuardInput.checked ? "true" : "false",
        );
    } catch (_) { /* localStorage unavailable */ }
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

function setInputsEnabled(enabled) {
    characterInput.disabled = !enabled;
    effectiveInput.disabled = !enabled;
    toneShapeInput.disabled = !enabled;
    receiverBedInput.disabled = !enabled;
    cadenceVariationInput.disabled = !enabled;
    trinkeyBuzzerInput.disabled = !enabled;
    playTestButton.disabled = !enabled;
    saveTestButton.disabled = !enabled;
}

function currentSettings() {
    const character = Number(characterInput.value);
    const effective = Number(effectiveInput.value);
    const toneShape = Number(toneShapeInput.value);
    const receiverBed = Number(receiverBedInput.value);
    const cadenceVariation = Number(cadenceVariationInput.value);
    const trinkeyBuzzerEnabled = trinkeyBuzzerInput.checked;
    return {
        character,
        effective,
        toneShape,
        receiverBed,
        cadenceVariation,
        trinkeyBuzzerEnabled,
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
    const { character, effective, toneShape, receiverBed, cadenceVariation } = currentSettings();
    if (!Number.isInteger(character) || character <= 0) {
        return "Character speed must be a positive whole number.";
    }
    if (!Number.isInteger(effective) || effective <= 0) {
        return "Effective speed must be a positive whole number.";
    }
    if (effective > character) {
        return "Effective speed cannot exceed character speed.";
    }
    if (!Number.isInteger(toneShape) || toneShape < 0 || toneShape > 10) {
        return "Tone Shape must be between 0 and 10.";
    }
    if (!Number.isInteger(receiverBed) || receiverBed < 0 || receiverBed > 10) {
        return "Receiver Bed must be between 0 and 10.";
    }
    if (!Number.isInteger(cadenceVariation) || cadenceVariation < 0 || cadenceVariation > 5) {
        return "Cadence Variation must be between 0 and 5.";
    }
    return "";
}

function isDirty() {
    if (!savedSettings) return false;
    const current = currentSettings();
    return Object.keys(savedSettings).some((key) => current[key] !== savedSettings[key]);
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
    toneShapeInput.value = event.tone_shape;
    receiverBedInput.value = event.receiver_bed;
    cadenceVariationInput.value = event.cadence_variation;
    trinkeyBuzzerInput.checked = Boolean(event.trinkey_buzzer_enabled);
    savedSettings = {
        character: event.character_wpm,
        effective: event.effective_wpm,
        toneShape: event.tone_shape,
        receiverBed: event.receiver_bed,
        cadenceVariation: event.cadence_variation,
        trinkeyBuzzerEnabled: Boolean(event.trinkey_buzzer_enabled),
    };
    updateSummaries();
    const prefix = isSaving ? "saved" : "ready";
    isSaving = false;
    setStatus(
        "connected",
        `${prefix} - ${event.character_wpm} WPM characters / ${event.effective_wpm} WPM effective`
    );
    setInputsEnabled(true);
    updateSaveState();
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

    const {
        character,
        effective,
        toneShape,
        receiverBed,
        cadenceVariation,
        trinkeyBuzzerEnabled,
    } = currentSettings();
    setInputsEnabled(false);
    isSaving = true;
    updateSaveState();
    setStatus("connected", "saving");
    socket.send(
        JSON.stringify({
            action: "set-audio-settings",
            character_wpm: character,
            effective_wpm: effective,
            tone_shape: toneShape,
            receiver_bed: receiverBed,
            cadence_variation: cadenceVariation,
            trinkey_buzzer_enabled: trinkeyBuzzerEnabled,
        })
    );
});

function testMessagePayload() {
    const { character, effective, toneShape, receiverBed, cadenceVariation } = currentSettings();
    return {
        character_wpm: character,
        effective_wpm: effective,
        tone_shape: toneShape,
        receiver_bed: receiverBed,
        cadence_variation: cadenceVariation,
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
    toneShapeInput,
    receiverBedInput,
    cadenceVariationInput,
].forEach((input) => input.addEventListener("input", onSettingsInput));

trinkeyBuzzerInput.addEventListener("change", onSettingsInput);

connect();
