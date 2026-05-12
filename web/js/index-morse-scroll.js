/*
 * Copy 653 landing-page Morse readout.
 *
 * Decorative only: displays a single, right-aligned symbol/rhythm sample in the
 * narrow band between the title rule and the navigation rule, changing at a
 * slow two-second cadence.
 */
(function () {
    "use strict";

    var UPDATE_MS = 2000;

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

    function makeSpan(className, text) {
        var span = document.createElement("span");
        span.className = className;
        span.textContent = text;
        return span;
    }

    function render(track) {
        var token = randomItem(MORSE);
        var item = document.createElement("span");
        item.className = "morse-scroll__item";

        item.appendChild(makeSpan("morse-scroll__bar", "| "));
        item.appendChild(makeSpan("morse-scroll__symbol", token[0]));
        item.appendChild(document.createTextNode("  "));
        item.appendChild(makeSpan("morse-scroll__rhythm", token[1]));
        item.appendChild(document.createTextNode("  "));
        item.appendChild(makeSpan("morse-scroll__bar", "|"));

        track.replaceChildren(item);
    }

    document.addEventListener("DOMContentLoaded", function () {
        var track = document.querySelector("[data-morse-scroll-track]");
        if (!track) return;

        render(track);
        window.setInterval(function () {
            render(track);
        }, UPDATE_MS);
    });
}());
