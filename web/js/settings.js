// Copy - Settings page.
//
// This page writes the shared [audio] timing keys used by every listening
// environment. User-facing labels follow established Morse learning terms:
// Koch = character speed, Farnsworth = effective speed after spacing.

const wsUrl = `ws://${location.host}/ws`;
const form = document.getElementById("audio-settings-form");
const kochInput = document.getElementById("koch-wpm");
const farnsworthInput = document.getElementById("farnsworth-wpm");
const saveButton = document.getElementById("save-audio-settings");
const statusEl = document.getElementById("settings-status");

let socket = null;
let isSaving = false;

function setStatus(status, text) {
    statusEl.dataset.status = status;
    statusEl.textContent = text;
}

function setFormEnabled(enabled) {
    kochInput.disabled = !enabled;
    farnsworthInput.disabled = !enabled;
    saveButton.disabled = !enabled;
}

function currentTiming() {
    const koch = Number(kochInput.value);
    const farnsworth = Number(farnsworthInput.value);
    return { koch, farnsworth };
}

function validateTiming() {
    const { koch, farnsworth } = currentTiming();
    if (!Number.isInteger(koch) || koch <= 0) {
        return "Koch WPM must be a positive whole number.";
    }
    if (!Number.isInteger(farnsworth) || farnsworth <= 0) {
        return "Farnsworth WPM must be a positive whole number.";
    }
    if (farnsworth > koch) {
        return "Farnsworth WPM cannot exceed Koch WPM.";
    }
    return "";
}

function renderAudioSettings(event) {
    kochInput.value = event.koch_wpm;
    farnsworthInput.value = event.farnsworth_wpm;
    const mode = event.farnsworth_enabled ? "Farnsworth spacing active" : "standard spacing";
    const prefix = isSaving ? "saved" : "ready";
    isSaving = false;
    setStatus("connected", `${prefix} - ${mode}`);
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

    const { koch, farnsworth } = currentTiming();
    setFormEnabled(false);
    isSaving = true;
    setStatus("connected", "saving");
    socket.send(
        JSON.stringify({
            action: "set-audio-settings",
            koch_wpm: koch,
            farnsworth_wpm: farnsworth,
        })
    );
});

kochInput.addEventListener("input", () => {
    const validationError = validateTiming();
    if (!validationError) setStatus("connected", "ready");
});

farnsworthInput.addEventListener("input", () => {
    const validationError = validateTiming();
    if (!validationError) setStatus("connected", "ready");
});

connect();
