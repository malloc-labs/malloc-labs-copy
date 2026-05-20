// One-shot MIDI Program Change + Control Change to the Trinkey keyer
// firmware: keyer mode (PC) and dit duration / WPM (CC1).
//
// Path A in the design doc: the browser owns the Trinkey on both
// directions of the cable. Copy stores the intended mode + WPM and
// pushes them when the user changes a value or clicks Sync now. Never
// on page load / WS reconnect — that would burn EEPROM write cycles on
// the SAMD21 for no benefit. The firmware writes EEPROM on every PC
// and on every CC1, so each call here is up to two writes.
//
// PC numbers come from vail-adapter/keyers.cpp `allKeyers[]` ordering
// and must stay in lockstep with the firmware. CC1 is the dit duration
// in units of 2 ms (so value = dit_ms / 2, where dit_ms = 1200 / WPM
// at PARIS). See vail-adapter/MIDI_INTEGRATION_SPEC.md.

import { selectTrinkeyDevice } from "./trinkey-device.js";

export const KEYER_MODE_PROGRAM_NUMBERS = Object.freeze({
    iambic_a: 7,
    ultimatic: 5,
});

export const TRINKEY_SYNC_RESULT = Object.freeze({
    SENT: "sent",
    UNKNOWN_MODE: "unknown-mode",
    MIDI_UNAVAILABLE: "midi-unavailable",
    MIDI_BLOCKED: "midi-blocked",
    NO_OUTPUT: "no-output",
    SEND_FAILED: "send-failed",
});

// CC1 carries dit duration as value × 2 ms; valid MIDI range is 1-127
// (the firmware accepts the full range, but 0 would be nonsensical).
function ditCcValueForWpm(wpm) {
    if (!Number.isFinite(wpm) || wpm <= 0) return null;
    const ditMs = 1200 / wpm;
    const raw = Math.round(ditMs / 2);
    return Math.max(1, Math.min(127, raw));
}

export async function sendTrinkeySync({ mode, wpm } = {}) {
    const programNumber = mode != null ? KEYER_MODE_PROGRAM_NUMBERS[mode] : null;
    if (mode != null && programNumber === undefined) {
        return { result: TRINKEY_SYNC_RESULT.UNKNOWN_MODE, mode };
    }

    const ccValue = wpm != null ? ditCcValueForWpm(wpm) : null;

    if (!navigator.requestMIDIAccess) {
        return { result: TRINKEY_SYNC_RESULT.MIDI_UNAVAILABLE };
    }

    let access;
    try {
        access = await navigator.requestMIDIAccess({ sysex: false });
    } catch (error) {
        return {
            result: TRINKEY_SYNC_RESULT.MIDI_BLOCKED,
            detail: error?.message || "",
        };
    }

    const output = selectTrinkeyDevice(access.outputs);
    if (!output) {
        return { result: TRINKEY_SYNC_RESULT.NO_OUTPUT };
    }

    const sent = {};
    try {
        if (programNumber !== null) {
            // 0xC0 = Program Change on channel 1.
            output.send([0xc0, programNumber]);
            sent.mode = mode;
        }
        if (ccValue !== null) {
            // 0xB0 0x01 = Control Change 1 (dit duration) on channel 1.
            output.send([0xb0, 0x01, ccValue]);
            sent.wpm = wpm;
        }
    } catch (error) {
        return {
            result: TRINKEY_SYNC_RESULT.SEND_FAILED,
            detail: error?.message || "",
            output_name: output.name || "",
            sent,
        };
    }

    return {
        result: TRINKEY_SYNC_RESULT.SENT,
        sent,
        program_number: programNumber,
        cc1_value: ccValue,
        output_name: output.name || "",
    };
}
