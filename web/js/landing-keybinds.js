/*
 * Landing-page keyboard accelerators.
 *
 * Any anchor with `aria-keyshortcuts="X"` becomes activatable by
 * pressing that letter. The matching letter is also underlined inline
 * in the link label (handled in markup). Skips when a modifier key is
 * held or focus is in an editable element so it never fights a real
 * text field.
 *
 * Lookup is done at keypress time rather than at script-init time —
 * back-links rendered by custom elements (<copy-landing-header>,
 * <copy-header>) may not be hydrated yet when this defer-script runs.
 */
(function () {
    "use strict";

    document.addEventListener("keydown", (event) => {
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        const target = event.target;
        if (target instanceof HTMLElement) {
            const tag = target.tagName;
            if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
        }
        const k = event.key.toLowerCase();
        if (k.length !== 1) return;
        const links = document.querySelectorAll("a[aria-keyshortcuts]");
        for (const a of links) {
            const shortcut = (a.getAttribute("aria-keyshortcuts") || "").trim().toLowerCase();
            if (shortcut === k) {
                event.preventDefault();
                a.click();
                return;
            }
        }
    });
}());
