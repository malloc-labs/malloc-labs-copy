// UI-only Morse display helpers.
//
// Engine and audio code use canonical ASCII patterns: "." for dit and
// "-" for dah. Browser rendering uses typographic marks with explicit
// spaces so single and repeated dahs have stable visual weight.

const DISPLAY_MARKS = {
    ".": "·",
    "-": "—",
};

export function displayMorsePattern(pattern) {
    return [...pattern].map((mark) => DISPLAY_MARKS[mark] ?? mark).join(" ");
}
