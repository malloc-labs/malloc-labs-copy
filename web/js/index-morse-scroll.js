/*
 * index-morse-scroll.js — faint decorative Morse ticker for the Copy 653 index.
 *
 * The strip is intentionally aria-hidden in markup. It is a visual texture only,
 * not training content or a navigation control.
 */
(function () {
    var WPM = 20;
    var CHARS_PER_STANDARD_WORD = 5;
    var MIN_CYCLE_SECONDS = 28;
    var REFRESH_BEATS = 4;

    var MORSE = [
        ["A", "Dit Dah"],
        ["B", "Dah Dit Dit Dit"],
        ["C", "Dah Dit Dah Dit"],
        ["D", "Dah Dit Dit"],
        ["E", "Dit"],
        ["F", "Dit Dit Dah Dit"],
        ["G", "Dah Dah Dit"],
        ["H", "Dit Dit Dit Dit"],
        ["I", "Dit Dit"],
        ["J", "Dit Dah Dah Dah"],
        ["K", "Dah Dit Dah"],
        ["L", "Dit Dah Dit Dit"],
        ["M", "Dah Dah"],
        ["N", "Dah Dit"],
        ["O", "Dah Dah Dah"],
        ["P", "Dit Dah Dah Dit"],
        ["Q", "Dah Dah Dit Dah"],
        ["R", "Dit Dah Dit"],
        ["S", "Dit Dit Dit"],
        ["T", "Dah"],
        ["U", "Dit Dit Dah"],
        ["V", "Dit Dit Dit Dah"],
        ["W", "Dit Dah Dah"],
        ["X", "Dah Dit Dit Dah"],
        ["Y", "Dah Dit Dah Dah"],
        ["Z", "Dah Dah Dit Dit"],
        ["1", "Dit Dah Dah Dah Dah"],
        ["2", "Dit Dit Dah Dah Dah"],
        ["3", "Dit Dit Dit Dah Dah"],
        ["4", "Dit Dit Dit Dit Dah"],
        ["5", "Dit Dit Dit Dit Dit"],
        ["6", "Dah Dit Dit Dit Dit"],
        ["7", "Dah Dah Dit Dit Dit"],
        ["8", "Dah Dah Dah Dit Dit"],
        ["9", "Dah Dah Dah Dah Dit"],
        ["0", "Dah Dah Dah Dah Dah"]
    ];

    function randomItem(items) {
        return items[Math.floor(Math.random() * items.length)];
    }

    function makeToken() {
        var item = randomItem(MORSE);
        return item[0] + " / " + item[1];
    }

    function makeLine(count) {
        var tokens = [];
        for (var i = 0; i < count; i += 1) {
            tokens.push(makeToken());
        }
        return tokens.join("     ");
    }

    function render(track) {
        var line = makeLine(18);
        var cycleSeconds = Math.max(MIN_CYCLE_SECONDS, Math.ceil((line.length / (WPM * CHARS_PER_STANDARD_WORD)) * 60));

        track.style.setProperty("--morse-scroll-duration", cycleSeconds + "s");
        track.replaceChildren();

        [line, line].forEach(function (text) {
            var span = document.createElement("span");
            span.className = "morse-scroll__line";
            span.textContent = text;
            track.appendChild(span);
        });

        return cycleSeconds;
    }

    document.addEventListener("DOMContentLoaded", function () {
        var track = document.querySelector("[data-morse-scroll-track]");
        if (!track) return;

        var cycleSeconds = render(track);
        window.setInterval(function () {
            cycleSeconds = render(track);
        }, cycleSeconds * REFRESH_BEATS * 1000);
    });
}());
