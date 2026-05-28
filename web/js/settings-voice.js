// Settings → Voice tab.
//
// Renders /api/voice/status, the merged lexicon table, and the per-file
// JSON dumps. The test dialog opens a real WebSocket to /voice/ws, runs
// an AudioWorklet at 16 kHz mono, ships Int16 PCM, and shows the
// recogniser's partial/final/symbol events live alongside a peak level
// meter.
//
// Per spec §8.3 the listening *page* has an affordance budget of 5;
// this is the settings page, where verification surfaces live.

const SAMPLE_RATE = 16_000;

const statusEl       = document.getElementById("settings-voice-status");
const tableBody      = document.querySelector("#settings-voice-lexicon-table tbody");
const filesEl        = document.getElementById("settings-voice-lexicon-files");
const formEl         = document.getElementById("settings-voice-form");
const languageInput  = document.getElementById("settings-voice-language");
const modelPathInput = document.getElementById("settings-voice-model-path");
const saveStatusEl   = document.getElementById("settings-voice-save-status");
const testOpenBtn    = document.getElementById("settings-voice-test-open");
const testDialog     = document.getElementById("settings-voice-test-dialog");
const testStartBtn   = document.getElementById("settings-voice-test-start");
const testStateEl    = document.getElementById("settings-voice-test-state");
const testMeterEl    = document.getElementById("settings-voice-test-meter");
const testPartialEl  = document.getElementById("settings-voice-test-partial");
const testFinalEl    = document.getElementById("settings-voice-test-final");
const testSymbolEl   = document.getElementById("settings-voice-test-symbol");

// ─── Main /ws connection (config read/write) ─────────────────────────────────

let mainSocket = null;

function _connectMainSocket() {
    if (mainSocket && (mainSocket.readyState === WebSocket.OPEN
                       || mainSocket.readyState === WebSocket.CONNECTING)) {
        return mainSocket;
    }
    const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
    mainSocket = new WebSocket(url);
    mainSocket.addEventListener("message", (ev) => {
        let event;
        try { event = JSON.parse(ev.data); } catch { return; }
        if (event.type === "voice-settings") {
            _applyVoiceSettingsEvent(event);
        } else if (event.type === "error" && event.reason === "invalid-voice-settings") {
            _setSaveStatus(`error: ${event.detail || "invalid settings"}`, "error");
        }
    });
    mainSocket.addEventListener("open", () => {
        mainSocket.send(JSON.stringify({ action: "get-voice-settings" }));
    });
    return mainSocket;
}

function _applyVoiceSettingsEvent(event) {
    if (languageInput && !languageInput.matches(":focus")) {
        languageInput.value = event.language ?? "";
    }
    if (modelPathInput && !modelPathInput.matches(":focus")) {
        modelPathInput.value = event.model_path ?? "";
    }
    _setField("language", event.language ?? "—");
    _setField("model_path", event.model_path ?? "(unset)");
    _setField("model_path_resolved", event.model_path_resolved ?? "—");
    _setField("model_exists", _yesNo(event.model_exists));
    // The voice-settings event doesn't carry vosk_installed / ready, so
    // re-fetch the HTTP status to keep the dependent fields fresh.
    refreshStatus();
}

function _setSaveStatus(text, kind = "info") {
    if (!saveStatusEl) return;
    saveStatusEl.textContent = text;
    saveStatusEl.dataset.kind = kind;
}

if (formEl) {
    formEl.addEventListener("submit", (event) => {
        event.preventDefault();
        const language = (languageInput.value || "").trim();
        const modelPathRaw = (modelPathInput.value || "").trim();
        if (!language) {
            _setSaveStatus("language is required", "error");
            return;
        }
        const ws = _connectMainSocket();
        _setSaveStatus("saving…", "info");
        const send = () => ws.send(JSON.stringify({
            action: "set-voice-settings",
            language,
            model_path: modelPathRaw || null,
        }));
        if (ws.readyState === WebSocket.OPEN) {
            send();
        } else {
            ws.addEventListener("open", send, { once: true });
        }
        // The voice-settings echo handler clears the saving message by
        // refreshing the status grid; show a confirmation after that.
        const ackOnce = (ev) => {
            let msg;
            try { msg = JSON.parse(ev.data); } catch { return; }
            if (msg.type === "voice-settings") {
                _setSaveStatus("saved", "ok");
                ws.removeEventListener("message", ackOnce);
            } else if (msg.type === "error" && msg.reason === "invalid-voice-settings") {
                ws.removeEventListener("message", ackOnce);
            }
        };
        ws.addEventListener("message", ackOnce);
    });
}

// ─── Status ──────────────────────────────────────────────────────────────────

async function refreshStatus() {
    if (!statusEl) return;
    try {
        const res = await fetch("/api/voice/status", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        _setField("language", data.language ?? "—");
        _setField("model_path", data.model_path ?? "(unset)");
        _setField("model_path_resolved", data.model_path_resolved ?? "—");
        _setField("model_exists", _yesNo(data.model_exists));
        _setField("vosk_installed", _yesNo(data.vosk_installed));
        _setField("ready", _yesNo(data.ready));
    } catch (err) {
        statusEl.querySelectorAll("dd").forEach((dd) => (dd.textContent = `error: ${err.message}`));
    }
}

function _setField(name, value) {
    const dd = statusEl.querySelector(`dd[data-field="${name}"]`);
    if (dd) dd.textContent = value;
}

function _yesNo(value) {
    if (value === true)  return "yes";
    if (value === false) return "no";
    return "—";
}

// ─── Lexicon ─────────────────────────────────────────────────────────────────

async function refreshLexicon() {
    if (!tableBody || !filesEl) return;
    try {
        const res = await fetch("/api/voice/lexicon?language=en", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        _renderMerged(data.merged, data.error);
        _renderFiles(data.files || []);
    } catch (err) {
        tableBody.replaceChildren();
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 2;
        td.textContent = `error: ${err.message}`;
        tr.appendChild(td);
        tableBody.appendChild(tr);
    }
}

function _renderMerged(merged, error) {
    tableBody.replaceChildren();
    if (error) {
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 2;
        td.textContent = error;
        tr.appendChild(td);
        tableBody.appendChild(tr);
        return;
    }
    if (!merged) return;
    for (const symbol of Object.keys(merged).sort()) {
        const tr = document.createElement("tr");
        const symCell = document.createElement("td");
        symCell.className = "cell-mono";
        symCell.textContent = symbol;
        const phraseCell = document.createElement("td");
        phraseCell.textContent = merged[symbol].join(", ");
        tr.append(symCell, phraseCell);
        tableBody.appendChild(tr);
    }
}

function _renderFiles(files) {
    filesEl.replaceChildren();
    for (const file of files) {
        const details = document.createElement("details");
        details.className = "settings-voice-file";
        const summary = document.createElement("summary");
        summary.textContent = file.name;
        const pre = document.createElement("pre");
        pre.textContent = JSON.stringify(file.json, null, 2);
        details.append(summary, pre);
        filesEl.appendChild(details);
    }
}

// ─── Test dialog ─────────────────────────────────────────────────────────────

const test = {
    ws: null,
    ctx: null,
    stream: null,
    node: null,
    running: false,
    meterAnimation: 0,
};

if (testOpenBtn && testDialog) {
    testOpenBtn.addEventListener("click", () => {
        _resetTestUi();
        testDialog.showModal();
    });
    testDialog.addEventListener("close", () => {
        _teardownTest("Idle");
    });
}

if (testStartBtn) {
    testStartBtn.addEventListener("click", async () => {
        if (test.running) {
            _teardownTest("Idle");
            return;
        }
        try {
            await _startTest();
        } catch (err) {
            _teardownTest(`Failed: ${err.message || err}`);
        }
    });
}

function _resetTestUi() {
    testStateEl.textContent = "Idle";
    testPartialEl.textContent = "—";
    testFinalEl.textContent = "—";
    testSymbolEl.textContent = "—";
    testMeterEl.style.width = "0%";
    testStartBtn.textContent = "Start listening";
}

async function _startTest() {
    testStateEl.textContent = "Connecting…";
    const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/voice/ws`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    test.ws = ws;
    // Identity so we can detect "torn down during setup" after each await.
    const session = (test.session = Symbol("voice-test-session"));

    let onReady;
    const readyPromise = new Promise((resolve, reject) => {
        onReady = { resolve, reject };
    });

    ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.type === "ready") {
            onReady.resolve();
            return;
        }
        if (msg.type === "error") {
            onReady.reject(new Error(msg.message || msg.reason || "engine error"));
            _teardownTest(`Engine: ${msg.message || msg.reason}`);
            return;
        }
        if (!test.running) return;
        if (msg.type === "partial") {
            testPartialEl.textContent = msg.text || "—";
            if (msg.symbol) testSymbolEl.textContent = msg.symbol;
        } else if (msg.type === "final") {
            testFinalEl.textContent = msg.text || "—";
            testPartialEl.textContent = "—";
            testSymbolEl.textContent = msg.symbol || "—";
        }
    };
    ws.onclose = () => {
        onReady.reject(new Error("WebSocket closed before ready"));
        if (test.session === session) _teardownTest("Disconnected");
    };
    ws.onerror = () => (testStateEl.textContent = "WebSocket error");

    await new Promise((resolve, reject) => {
        ws.addEventListener("open", resolve, { once: true });
        ws.addEventListener("error", reject, { once: true });
    });
    if (test.session !== session) return;

    // Wait for the engine to confirm the recogniser is live before
    // prompting the user for mic access. If the engine sent an error
    // instead, this rejects and the catch in the click handler shows it.
    testStateEl.textContent = "Waiting for recogniser…";
    await readyPromise;
    if (test.session !== session) return;

    testStateEl.textContent = "Requesting microphone…";
    const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
            channelCount: 1,
            sampleRate: SAMPLE_RATE,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
        },
    });
    if (test.session !== session) { stream.getTracks().forEach((t) => t.stop()); return; }
    test.stream = stream;

    const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
    test.ctx = ctx;
    await ctx.audioWorklet.addModule("../js/voice-recorder-worklet.js");
    if (test.session !== session) { try { ctx.close(); } catch {} return; }

    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, "voice-recorder-processor");
    test.node = node;

    node.port.onmessage = (ev) => {
        const { pcm, peak } = ev.data;
        if (ws.readyState === WebSocket.OPEN) {
            ws.send(_float32ToInt16(pcm).buffer);
        }
        _renderMeter(peak);
    };

    source.connect(node);
    // Intentionally NOT connecting node → ctx.destination.

    test.running = true;
    testStartBtn.textContent = "Stop";
    testStateEl.textContent = `Listening · ${ctx.sampleRate} Hz`;
}

function _teardownTest(stateText) {
    test.running = false;
    test.session = null;
    if (test.node) {
        try { test.node.disconnect(); } catch {}
        test.node = null;
    }
    if (test.ctx) {
        try { test.ctx.close(); } catch {}
        test.ctx = null;
    }
    if (test.stream) {
        test.stream.getTracks().forEach((t) => t.stop());
        test.stream = null;
    }
    if (test.ws) {
        try { test.ws.close(); } catch {}
        test.ws = null;
    }
    testStartBtn.textContent = "Start listening";
    testStateEl.textContent = stateText;
    testMeterEl.style.width = "0%";
}

function _float32ToInt16(input) {
    const out = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) {
        const s = Math.max(-1, Math.min(1, input[i]));
        out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return out;
}

function _renderMeter(peak) {
    // Peak is [0, 1]. Render as percent width. No animation library —
    // CSS handles the transition on width.
    const pct = Math.min(100, Math.round(peak * 100));
    testMeterEl.style.width = `${pct}%`;
}

// ─── Activate when tab opens ─────────────────────────────────────────────────

const voiceTabBtn = document.getElementById("settings-tab-voice");
if (voiceTabBtn) {
    let loaded = false;
    voiceTabBtn.addEventListener("click", () => {
        if (loaded) return;
        loaded = true;
        refreshStatus();
        refreshLexicon();
        // Opens the main /ws lazily so the Voice tab can read and write
        // [voice] config. Other tabs already use their own /ws clients
        // (see settings.js); a second connection is the existing pattern.
        _connectMainSocket();
    });
}
