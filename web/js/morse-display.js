// UI-only Morse display helpers.
//
// Engine and audio code use canonical ASCII patterns: "." for dit and
// "-" for dah. Browser rendering uses typographic marks with explicit
// spaces so single and repeated dahs have stable visual weight.

const DISPLAY_MARKS = {
    ".": "·",
    "-": "—",
};

export const PATTERNS = {
    A: ".-",
    B: "-...",
    C: "-.-.",
    D: "-..",
    E: ".",
    F: "..-.",
    G: "--.",
    H: "....",
    I: "..",
    J: ".---",
    K: "-.-",
    L: ".-..",
    M: "--",
    N: "-.",
    O: "---",
    P: ".--.",
    Q: "--.-",
    R: ".-.",
    S: "...",
    T: "-",
    U: "..-",
    V: "...-",
    W: ".--",
    X: "-..-",
    Y: "-.--",
    Z: "--..",
    0: "-----",
    1: ".----",
    2: "..---",
    3: "...--",
    4: "....-",
    5: ".....",
    6: "-....",
    7: "--...",
    8: "---..",
    9: "----.",
    ".": ".-.-.-",
    ",": "--..--",
    "?": "..--..",
    "/": "-..-.",
    "=": "-...-",
};

export function displayMorsePattern(pattern) {
    return [...pattern].map((mark) => DISPLAY_MARKS[mark] ?? mark).join(" ");
}

export function spokenMorsePattern(pattern) {
    return [...pattern].map((mark) => (mark === "-" ? "Dah" : "dit")).join(" ");
}
