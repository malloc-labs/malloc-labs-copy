// One-shot MIDI Program Change to the Trinkey keyer firmware.
//
// Path A in the design doc: the browser owns the Trinkey on both
// directions of the cable. Copy stores the intended keyer mode and
// sends a PC when the user changes it or clicks Sync now. Never on
// page load / WS reconnect — that would burn EEPROM write cycles on
// the SAMD21 for no benefit.
//
// PC numbers come from vail-adapter/keyers.cpp `allKeyers[]` ordering
// and must stay in lockstep with the firmware. The firmware writes the
// new mode to EEPROM on every PC, so each call here is one write.

import { selectTrinkeyDevice } from "./trinkey-device.js";

export const KEYER_MODE_PROGRAM_NUMBERS = Object.freeze({
    iambic_a: 7,
    ultimatic: 5,
});

export const KEYER_MODE_SYNC_RESULT = Object.freeze({
    SENT: "sent",
    UNKNOWN_MODE: "unknown-mode",
    MIDI_UNAVAILABLE: "midi-unavailable",
    MIDI_BLOCKED: "midi-blocked",
    NO_OUTPUT: "no-output",
    SEND_FAILED: "send-failed",
});

export async function sendKeyerModeProgramChange(mode) {
    const programNumber = KEYER_MODE_PROGRAM_NUMBERS[mode];
    if (programNumber === undefined) {
        return { result: KEYER_MODE_SYNC_RESULT.UNKNOWN_MODE, mode };
    }

    if (!navigator.requestMIDIAccess) {
        return { result: KEYER_MODE_SYNC_RESULT.MIDI_UNAVAILABLE };
    }

    let access;
    try {
        access = await navigator.requestMIDIAccess({ sysex: false });
    } catch (error) {
        return {
            result: KEYER_MODE_SYNC_RESULT.MIDI_BLOCKED,
            detail: error?.message || "",
        };
    }

    const output = selectTrinkeyDevice(access.outputs);
    if (!output) {
        return { result: KEYER_MODE_SYNC_RESULT.NO_OUTPUT };
    }

    // 0xC0 = Program Change on channel 1. Same byte the firmware's
    // HandleMIDI() switch dispatches on.
    try {
        output.send([0xc0, programNumber]);
    } catch (error) {
        return {
            result: KEYER_MODE_SYNC_RESULT.SEND_FAILED,
            detail: error?.message || "",
            output_name: output.name || "",
        };
    }
    return {
        result: KEYER_MODE_SYNC_RESULT.SENT,
        mode,
        program_number: programNumber,
        output_name: output.name || "",
    };
}
