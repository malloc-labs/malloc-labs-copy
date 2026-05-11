// Copy - Settings page.
//
// This page writes the shared [audio] timing keys used by every listening
// environment. User-facing labels follow established Morse learning terms:
// character speed = symbol cadence, effective speed = pressure after spacing.

const wsUrl = `ws://${location.host}/ws`;
const form = document.getElementById("audio-settings-form");
const characterInput = document.getElementById("character-wpm");
const effectiveInput = document.getElementById("effective-wpm");
const saveButton = document.getElementById("save-audio-settings");
const statusEl = document.getElementById("settings-status");
const characterSummary = document.getElementById("character-speed-summary");
const effectiveSummary = document.getElementById("effective-speed-summary");

let socket = null;
let isSaving = false;

function setStatus(status, text) {
    statusEl.dataset.status = status;
    statusEl.textContent = text;
}

function setFormEnabled(enabled) {
    characterInput.disabled = !enabled;
    effectiveInput.disabled = !enabled;
    saveButton.disabled = !enabled;
}

function currentTiming() {
    const character = Number(characterInput.value);
    const effective = Number(effectiveInput.value);
    return { character, effective };
}

function updateSummaries() {
    const { character, effective } = currentTiming();
    characterSummary.textContent =
        Number.isFinite(character) && character > 0 ? `${character} WPM` : "Character WPM";
    effectiveSummary.textContent =
        Number.isFinite(effective) && effective > 0 ? `${effective} WPM` : "Effective WPM";
}

function validateTiming() {
    const { character, effective } = currentTiming();
    if (!Number.isInteger(character) || character <= 0) {
        return "Character speed must be a positive whole number.";
    }
    if (!Number.isInteger(effective) || effective <= 0) {
        return "Effective speed must be a positive whole number.";
    }
    if (effective > character) {
        return "Effective speed cannot exceed character speed.";
    }
    return "";
}

function renderAudioSettings(event) {
    characterInput.value = event.character_wpm;
    effectiveInput.value = event.effective_wpm;
    updateSummaries();
    const prefix = isSaving ? "saved" : "ready";
    isSaving = false;
    setStatus(
        "connected",
        `${prefix} - ${event.character_wpm} WPM characters / ${event.effective_wpm} WPM effective`
    );
    setFormEnabled(true);
}

function connect() {
    setFormEnabled(false);
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
            setFormEnabled(true);
        }
    });

    socket.addEventListener("close", () => {
        isSaving = false;
        setFormEnabled(false);
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

    const validationError = validateTiming();
    if (validationError) {
        setStatus("error", validationError);
        return;
    }

    const { character, effective } = currentTiming();
    setFormEnabled(false);
    isSaving = true;
    setStatus("connected", "saving");
    socket.send(
        JSON.stringify({
            action: "set-audio-settings",
            character_wpm: character,
            effective_wpm: effective,
        })
    );
});

characterInput.addEventListener("input", () => {
    updateSummaries();
    const validationError = validateTiming();
    if (!validationError) setStatus("connected", "ready");
});

effectiveInput.addEventListener("input", () => {
    updateSummaries();
    const validationError = validateTiming();
    if (!validationError) setStatus("connected", "ready");
});

connect();
