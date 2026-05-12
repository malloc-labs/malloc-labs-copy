// Copy - Settings page.
//
// This page writes the shared [audio] timing keys used by every listening
// environment. User-facing labels follow established Morse learning terms:
// character speed = symbol cadence, effective speed = pressure after spacing.

const wsUrl = `ws://${location.host}/ws`;
const form = document.getElementById("audio-settings-form");
const characterInput = document.getElementById("character-wpm");
const effectiveInput = document.getElementById("effective-wpm");
const toneShapeInput = document.getElementById("tone-shape");
const receiverBedInput = document.getElementById("receiver-bed");
const cadenceVariationInput = document.getElementById("cadence-variation");
const saveButton = document.getElementById("save-audio-settings");
const statusEl = document.getElementById("settings-status");
const characterSummary = document.getElementById("character-speed-summary");
const effectiveSummary = document.getElementById("effective-speed-summary");
const toneShapeSummary = document.getElementById("tone-shape-summary");
const receiverBedSummary = document.getElementById("receiver-bed-summary");
const cadenceVariationSummary = document.getElementById("cadence-variation-summary");

let socket = null;
let isSaving = false;
let savedSettings = null;

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
}

function currentSettings() {
    const character = Number(characterInput.value);
    const effective = Number(effectiveInput.value);
    const toneShape = Number(toneShapeInput.value);
    const receiverBed = Number(receiverBedInput.value);
    const cadenceVariation = Number(cadenceVariationInput.value);
    return { character, effective, toneShape, receiverBed, cadenceVariation };
}

function updateSummaries() {
    const { character, effective, toneShape, receiverBed, cadenceVariation } = currentSettings();
    characterSummary.textContent =
        Number.isFinite(character) && character > 0 ? `${character} WPM` : "Character WPM";
    effectiveSummary.textContent =
        Number.isFinite(effective) && effective > 0 ? `${effective} WPM` : "Effective WPM";
    toneShapeSummary.textContent = Number.isInteger(toneShape) ? String(toneShape) : "-";
    receiverBedSummary.textContent = Number.isInteger(receiverBed) ? String(receiverBed) : "-";
    cadenceVariationSummary.textContent =
        Number.isInteger(cadenceVariation) ? String(cadenceVariation) : "-";
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

    return { validationError, dirty };
}

function renderAudioSettings(event) {
    characterInput.value = event.character_wpm;
    effectiveInput.value = event.effective_wpm;
    toneShapeInput.value = event.tone_shape;
    receiverBedInput.value = event.receiver_bed;
    cadenceVariationInput.value = event.cadence_variation;
    savedSettings = {
        character: event.character_wpm,
        effective: event.effective_wpm,
        toneShape: event.tone_shape,
        receiverBed: event.receiver_bed,
        cadenceVariation: event.cadence_variation,
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
        }
    });

    socket.addEventListener("close", () => {
        isSaving = false;
        setInputsEnabled(false);
        saveButton.disabled = true;
        saveButton.classList.remove("btn--primary");
        setStatus("disconnected", "disconnected");
    });

    socket.addEventListener("error", () => {
        isSaving = false;
        setStatus("error", "connection error");
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

    const { character, effective, toneShape, receiverBed, cadenceVariation } = currentSettings();
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
        })
    );
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

connect();
