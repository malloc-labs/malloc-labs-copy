// AudioWorklet processor: forwards each input frame to the main
// thread as a Float32Array copy plus a peak amplitude in [0, 1].
// Mono only — channel 0.

class VoiceRecorderProcessor extends AudioWorkletProcessor {
    process(inputs) {
        const input = inputs[0];
        if (!input || input.length === 0) return true;
        const channel = input[0];
        if (!channel || channel.length === 0) return true;

        let peak = 0;
        for (let i = 0; i < channel.length; i++) {
            const v = Math.abs(channel[i]);
            if (v > peak) peak = v;
        }

        const copy = new Float32Array(channel.length);
        copy.set(channel);
        this.port.postMessage({ pcm: copy, peak }, [copy.buffer]);
        return true;
    }
}

registerProcessor("voice-recorder-processor", VoiceRecorderProcessor);
