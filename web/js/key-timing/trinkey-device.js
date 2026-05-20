// Shared Trinkey device-name matcher.
//
// Used by midi-input.js to pick the input port and by trinkey-sync.js
// to pick the output port. Keeping them in one place ensures input and
// output selection cannot drift apart.

const TRINKEY_NAME_FRAGMENT = "trrs trinkey";

export function matchesTrinkeyName(name) {
    return typeof name === "string"
        && name.toLowerCase().includes(TRINKEY_NAME_FRAGMENT);
}

export function selectTrinkeyDevice(portMap) {
    const available = Array.from(portMap.values());
    return available.find((port) => matchesTrinkeyName(port.name))
        || available[0]
        || null;
}
