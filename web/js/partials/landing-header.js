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
//   title         — main title text (e.g. "Settings", "Koch Method")

class CopyLandingHeader extends HTMLElement {
    connectedCallback() {
        if (this._hydrated) return;
        this._hydrated = true;
        const kicker = this.getAttribute("kicker");
        const eyebrow = this.getAttribute("eyebrow");
        const eyebrowHref = this.getAttribute("eyebrow-href") ?? "index.html";
        const title = this.getAttribute("title") ?? "";
        let topLine = "";
        if (kicker) {
            topLine = `<p class="landing-kicker">${kicker}</p>`;
        } else if (eyebrow) {
            topLine = `<p class="eyebrow"><a href="${eyebrowHref}" class="back-link">${eyebrow}</a></p>`;
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
