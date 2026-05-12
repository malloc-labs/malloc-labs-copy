/*
 * index-morse-scroll.js — faint decorative Morse ticker for the Copy 653 index.
 *
 * The strip is intentionally aria-hidden in markup. It is a visual texture only,
 * not training content or a navigation control.
 */
(function () {
    var WPM = 24.2; // 20wpm experiment, increased twice by 10%.
    var CHARS_PER_STANDARD_WORD = 5;
    var MIN_CYCLE_SECONDS = 25;
    var REFRESH_BEATS = 4;

    var MORSE = [
        ["A", "dit Dah"],
        ["B", "Dah dit dit dit"],
        ["C", "Dah dit Dah dit"],
        ["D", "Dah dit dit"],
        ["E", "dit"],
        ["F", "dit dit Dah dit"],
        ["G", "Dah Dah dit"],
        ["H", "dit dit dit dit"],
        ["I", "dit dit"],
        ["J", "dit Dah Dah Dah"],
        ["K", "Dah dit Dah"],
        ["L", "dit Dah dit dit"],
        ["M", "Dah Dah"],
        ["N", "Dah dit"],
        ["O", "Dah Dah Dah"],
        ["P", "dit Dah Dah dit"],
        ["Q", "Dah Dah dit Dah"],
        ["R", "dit Dah dit"],
        ["S", "dit dit dit"],
        ["T", "Dah"],
        ["U", "dit dit Dah"],
        ["V", "dit dit dit Dah"],
        ["W", "dit Dah Dah"],
        ["X", "Dah dit dit Dah"],
        ["Y", "Dah dit Dah Dah"],
        ["Z", "Dah Dah dit dit"],
        ["1", "dit Dah Dah Dah Dah"],
        ["2", "dit dit Dah Dah Dah"],
        ["3", "dit dit dit Dah Dah"],
        ["4", "dit dit dit dit Dah"],
        ["5", "dit dit dit dit dit"],
        ["6", "Dah dit dit dit dit"],
        ["7", "Dah Dah dit dit dit"],
        ["8", "Dah Dah Dah dit dit"],
        ["9", "Dah Dah Dah Dah dit"],
        ["0", "Dah Dah Dah Dah Dah"]
    ];

    function randomItem(items) {
        return items[Math.floor(Math.random() * items.length)];
    }

    function makeTokens(count) {
        var tokens = [];
        for (var i = 0; i < count; i += 1) {
            tokens.push(randomItem(MORSE));
        }
        return tokens;
    }

    function tokenLength(token) {
        return 2 + token[0].length + 2 + token[1].length + 3;
    }

    function appendLine(track, tokens) {
        var line = document.createElement("span");
        line.className = "morse-scroll__line";

        tokens.forEach(function (token) {
            var item = document.createElement("span");
            item.className = "morse-scroll__item";

            var symbol = document.createElement("span");
            symbol.className = "morse-scroll__symbol";
            symbol.textContent = token[0];

            var rhythm = document.createElement("span");
            rhythm.className = "morse-scroll__rhythm";
            rhythm.textContent = token[1];

            item.appendChild(document.createTextNode("| "));
            item.appendChild(symbol);
            item.appendChild(document.createTextNode("  "));
            item.appendChild(rhythm);
            item.appendChild(document.createTextNode("  |"));
            line.appendChild(item);
        });

        track.appendChild(line);
    }

    function render(track) {
        var tokens = makeTokens(18);
        var lineLength = tokens.reduce(function (total, token) {
            return total + tokenLength(token);
        }, 0);
        var cycleSeconds = Math.max(MIN_CYCLE_SECONDS, Math.ceil((lineLength / (WPM * CHARS_PER_STANDARD_WORD)) * 60));

        track.style.setProperty("--morse-scroll-duration", cycleSeconds + "s");
        track.replaceChildren();
        appendLine(track, tokens);
        appendLine(track, tokens);

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
