// Copy — Key timing page sidetone.
//
// Owns the WebAudio sidetone (oscillator + gain envelope), the
// soundEnabled toggle state, and the audio-diagnostic row + soundToggle
// button rendering. Other modules read the audio state via the
// exported `sidetone` singleton (.configure, .keyDown, .keyUp, .mute,
// .unlock, .stateLabel) and the small accessor API below.

import { clamp, makeAccelLabel } from "./utils.js";
import { cadenceSpeakerEl, diagAudioEl, soundToggleEl } from "./dom.js";

const DEFAULT_TONE_HZ = 600;
const DEFAULT_AMPLITUDE = 0.3;
const DEFAULT_RAMP_SECONDS = 0.005;

let soundEnabled = false;

export function isSoundEnabled() {
    return soundEnabled;
}

class KeySidetone {
    constructor() {
        this.context = null;
        this.oscillator = null;
        this.gain = null;
        this.activeKeys = new Set();
        this.frequencyHz = DEFAULT_TONE_HZ;
        this.amplitude = DEFAULT_AMPLITUDE;
        this.rampSeconds = DEFAULT_RAMP_SECONDS;
        this.browserBlocked = false;
    }

    configure(event) {
        this.frequencyHz = Number(event.tone_frequency_hz) || this.frequencyHz;
        this.amplitude = clamp(Number(event.amplitude) || this.amplitude, 0, 1);
        this.rampSeconds = Math.max(
            (Number(event.envelope_ramp_ms) || DEFAULT_RAMP_SECONDS * 1000) / 1000,
            0.001,
        );
        if (this.oscillator) {
            this.oscillator.frequency.setValueAtTime(
                this.frequencyHz,
                this.context.currentTime,
            );
        }
        updateAudioDiagnostic();
    }

    ensureStarted() {
        if (this.context) return;

        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) {
            diagAudioEl.textContent = "unsupported";
            return;
        }

        this.context = new AudioContext();
        this.gain = this.context.createGain();
        this.gain.gain.setValueAtTime(0, this.context.currentTime);

        this.oscillator = this.context.createOscillator();
        this.oscillator.type = "sine";
        this.oscillator.frequency.setValueAtTime(this.frequencyHz, this.context.currentTime);
        this.oscillator.connect(this.gain);
        this.gain.connect(this.context.destination);
        this.oscillator.start();
    }

    async unlock() {
        this.ensureStarted();
        if (!this.context) {
            updateAudioDiagnostic();
            return false;
        }
        if (this.context.state === "running") {
            this.browserBlocked = false;
            updateAudioDiagnostic();
            return true;
        }

        try {
            await this.context.resume();
            this.browserBlocked = this.context.state !== "running";
            updateAudioDiagnostic();
            return this.context.state === "running";
        } catch {
            this.browserBlocked = true;
            updateAudioDiagnostic();
            return false;
        }
    }

    keyDown(note) {
        if (!soundEnabled) return;
        if (!this.context || this.context.state !== "running") {
            this.browserBlocked = true;
            updateAudioDiagnostic();
            return;
        }
        this.activeKeys.add(note);
        this.rampTo(this.amplitude);
    }

    keyUp(note) {
        this.activeKeys.delete(note);
        if (this.activeKeys.size === 0) {
            this.rampTo(0);
        }
    }

    mute() {
        this.activeKeys.clear();
        this.rampTo(0);
    }

    rampTo(value) {
        if (!this.context || !this.gain) return;
        const now = this.context.currentTime;
        this.gain.gain.cancelScheduledValues(now);
        this.gain.gain.setValueAtTime(this.gain.gain.value, now);
        this.gain.gain.linearRampToValueAtTime(value, now + this.rampSeconds);
        updateAudioDiagnostic();
    }

    stateLabel() {
        if (!soundEnabled || !this.context) return "click sound";
        if (this.context.state === "suspended") return "click sound";
        if (this.browserBlocked) return "blocked";
        return this.activeKeys.size > 0 ? "tone" : "ready";
    }
}

export const sidetone = new KeySidetone();

export function updateAudioDiagnostic() {
    diagAudioEl.textContent = sidetone.stateLabel();
    renderSoundToggleLabel();
}

function renderSoundToggleLabel() {
    if (soundEnabled) {
        soundToggleEl.replaceChildren(makeAccelLabel("m", "ute"));
        soundToggleEl.title = "Mute sidetone (M)";
        soundToggleEl.setAttribute("aria-keyshortcuts", "M");
    } else {
        soundToggleEl.replaceChildren(
            document.createTextNode("enable "),
            makeAccelLabel("s", "ound"),
        );
        soundToggleEl.title = "Enable sidetone (S)";
        soundToggleEl.setAttribute("aria-keyshortcuts", "S");
    }
    if (cadenceSpeakerEl) {
        cadenceSpeakerEl.dataset.state = soundEnabled ? "on" : "off";
    }
}

async function togglePower() {
    if (soundEnabled) {
        soundEnabled = false;
        sidetone.mute();
    } else {
        soundEnabled = await sidetone.unlock();
    }
    updateAudioDiagnostic();
}

export async function enableSidetone() {
    if (!soundEnabled) {
        soundEnabled = await sidetone.unlock();
        updateAudioDiagnostic();
    }
    return soundEnabled;
}

export function toggleSidetone() {
    togglePower();
}

soundToggleEl.addEventListener("click", togglePower);
