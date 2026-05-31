const VOICE_INPUT_DEVICE_KEY = "copy653_voice_input_device_id";

export function getVoiceInputDeviceId() {
    try {
        return localStorage.getItem(VOICE_INPUT_DEVICE_KEY) || "";
    } catch {
        return "";
    }
}

export function setVoiceInputDeviceId(deviceId) {
    try {
        if (deviceId) {
            localStorage.setItem(VOICE_INPUT_DEVICE_KEY, deviceId);
        } else {
            localStorage.removeItem(VOICE_INPUT_DEVICE_KEY);
        }
    } catch {
        // Ignore storage failures; browser default input still works.
    }
}

export function voiceInputAudioConstraints(deviceId = getVoiceInputDeviceId()) {
    const audio = {
        channelCount: 1,
        sampleRate: 16_000,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
    };
    if (deviceId) {
        audio.deviceId = { exact: deviceId };
    }
    return { audio };
}
