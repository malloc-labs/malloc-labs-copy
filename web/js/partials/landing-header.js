// <copy-landing-header> — landing-shell header for navigation and
// settings pages that do NOT connect to the engine (no status span,
// no speaker SVG). Light DOM (no shadow) so core.css applies
// unchanged. Includes the trailing <hr class="landing-rule">.
//
// Sibling partial is <copy-header>, which is used by pages that
// connect to the engine and need the status/speaker affordances.
//
// Attributes (set exactly one of kicker or eyebrow):
//   kicker        — text for the <p class="landing-kicker"> above
//                   the title; used by the root /index.html where
//                   there is no parent to link back to
//   eyebrow       — text for the back-link eyebrow (e.g. "Copy 653",
//                   "Guided Listening")
//   eyebrow-href  — href for the back-link; defaults to "index.html"
//                   (the sibling-landing convention). Subdirectory
//                   index pages override to "../index.html".
//   eyebrow-key   — single-letter accelerator for the back-link
//                   (e.g. "C" for "Copy 653"). Wraps the first
//                   matching letter in <u>, sets aria-keyshortcuts and
//                   title. Activation is wired by landing-keybinds.js.
//   title         — main title text (e.g. "Settings", "Koch Method")

function underlineAccel(text, key) {
    if (!key || !text) return text;
    const target = key[0].toLowerCase();
    const idx = text.toLowerCase().indexOf(target);
    if (idx === -1) return text;
    return `${text.slice(0, idx)}<u>${text[idx]}</u>${text.slice(idx + 1)}`;
}

class CopyLandingHeader extends HTMLElement {
    connectedCallback() {
        if (this._hydrated) return;
        this._hydrated = true;
        const kicker = this.getAttribute("kicker");
        const eyebrow = this.getAttribute("eyebrow");
        const eyebrowHref = this.getAttribute("eyebrow-href") ?? "index.html";
        const eyebrowKey = this.getAttribute("eyebrow-key");
        const title = this.getAttribute("title") ?? "";
        let topLine = "";
        if (kicker) {
            topLine = `<p class="landing-kicker">${kicker}</p>`;
        } else if (eyebrow) {
            const accel = eyebrowKey
                ? ` aria-keyshortcuts="${eyebrowKey}" title="${eyebrow} (${eyebrowKey.toUpperCase()})"`
                : "";
            const label = underlineAccel(eyebrow, eyebrowKey);
            topLine = `<p class="eyebrow"><a href="${eyebrowHref}" class="back-link"${accel}>${label}</a></p>`;
        }
        this.innerHTML = `
<header class="landing-header">
    ${topLine}
    <h1 class="landing-title">${title}</h1>
</header>
<hr class="landing-rule">`;
    }
}

customElements.define("copy-landing-header", CopyLandingHeader);
