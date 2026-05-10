/*
 * theme.js — blocking theme initialiser.
 *
 * Runs before CSS paint to prevent theme flash. Reads stored preference
 * from localStorage; falls back to system preference; defaults to dark.
 *
 * The toggle button shows the *opposite* theme label (the action, not
 * the current state), per the Malloc Rubicon design system §7.
 *
 * Usage: <script src="js/theme.js"></script>  (no defer, no type=module)
 */

(function () {
    var stored = localStorage.getItem("mr-theme");
    var theme;

    if (stored === "light" || stored === "dark") {
        theme = stored;
    } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
        theme = "light";
    } else {
        theme = "dark";
    }

    document.documentElement.setAttribute("data-theme", theme);

    // Wire the toggle button once the DOM is ready.
    document.addEventListener("DOMContentLoaded", function () {
        var btn = document.getElementById("theme-toggle");
        if (!btn) return;

        // Show the opposite label (the action).
        btn.textContent = theme === "dark" ? "light" : "dark";

        btn.addEventListener("click", function () {
            var current = document.documentElement.getAttribute("data-theme");
            var next = current === "dark" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", next);
            localStorage.setItem("mr-theme", next);
            btn.textContent = next === "dark" ? "light" : "dark";
        });

        // Respond to system preference changes when no stored value.
        if (!stored && window.matchMedia) {
            window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", function (e) {
                if (localStorage.getItem("mr-theme")) return;
                var sys = e.matches ? "light" : "dark";
                document.documentElement.setAttribute("data-theme", sys);
                btn.textContent = sys === "dark" ? "light" : "dark";
            });
        }
    });
}());
