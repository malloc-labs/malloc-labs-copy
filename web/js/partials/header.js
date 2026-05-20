// <copy-header> — landing-shell header shared across /key/ pages
// (and forthcoming for /koch/exercises.html). Light DOM (no shadow)
// so core.css / copy-653.css apply unchanged. Includes the trailing
// <hr class="landing-rule"> because every page that uses this header
// also uses that rule directly under it.
//
// Attributes:
//   eyebrow       — text for the back-link eyebrow (e.g. "Key",
//                   "Koch Method")
//   eyebrow-href  — href for the back-link; defaults to "index.html"
//                   to match the project convention of a sibling
//                   landing page
//   title         — main title text (e.g. "Cadence", "Freeplay")
//   speaker       — boolean; render the sidetone-state speaker SVG.
//                   /key/ pages that emit a tone set this; Koch
//                   pages do not.
//   keyer-mode    — boolean; render a small text badge that the page
//                   populates from the audio-settings WS event so the
//                   learner can see at a glance which keyer mode the
//                   firmware is configured for.
//
// Load order: this module must precede scripts that touch
// #cadence-speaker, #key-mode-badge, or the .status span
// (key-timing.js etc.).

const SPEAKER_SVG = `
                <svg class="cadence-speaker" id="cadence-speaker" data-state="off" viewBox="0 0 32 32" role="img" aria-label="Sidetone state">
                    <!-- IEEE 315 loudspeaker: rectangle body + trapezoidal cone -->
                    <rect x="6" y="11" width="6" height="10"/>
                    <polygon points="12,11 12,21 22,27 22,5"/>
                </svg>`;

const KEYER_MODE_BADGE = `<span class="key-mode-badge" id="key-mode-badge" data-keyer-mode="" aria-label="Keyer mode">—</span>`;

class CopyHeader extends HTMLElement {
    connectedCallback() {
        if (this._hydrated) return;
        this._hydrated = true;
        const eyebrow = this.getAttribute("eyebrow") ?? "";
        const eyebrowHref = this.getAttribute("eyebrow-href") ?? "index.html";
        const title = this.getAttribute("title") ?? "";
        const speakerSvg = this.hasAttribute("speaker") ? SPEAKER_SVG : "";
        const keyerModeBadge = this.hasAttribute("keyer-mode") ? KEYER_MODE_BADGE : "";
        this.innerHTML = `
<header class="landing-header">
    <p class="eyebrow"><a href="${eyebrowHref}" class="back-link">${eyebrow}</a></p>
    <h1 class="landing-title">
        <span class="landing-title__text">${title} <span class="status" data-status="connecting">connecting...</span></span>${keyerModeBadge}${speakerSvg}
    </h1>
</header>
<hr class="landing-rule">`;
    }
}

customElements.define("copy-header", CopyHeader);
