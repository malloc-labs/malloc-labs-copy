// <copy-sent> — collapsible sent-symbols panel shared by /key/ pages.
// Light DOM (no shadow) so core.css / copy-653.css apply unchanged.
// Identical on every host page today, so no attributes.
//
// Load order: this module must precede key-timing.js so element IDs
// (#sent-toggle, #sent-symbol, #sent-history) exist before handlers
// bind to them.

class CopySent extends HTMLElement {
    connectedCallback() {
        if (this._hydrated) return;
        this._hydrated = true;
        this.innerHTML = `
<section class="key-sent" aria-label="Sent symbols">
    <button type="button" class="key-sent__toggle" id="sent-toggle" aria-expanded="false" aria-controls="key-sent-body">
        <span class="key-sent__label" id="sent-toggle-label"></span>
        <span class="key-sent__arrow" id="sent-arrow" aria-hidden="true">▶</span>
    </button>
    <div class="key-sent__body" id="key-sent-body" hidden>
        <div class="key-sent-current" aria-live="polite">
            <span class="key-sent-symbol" id="sent-symbol">—</span>
        </div>
        <ol class="key-sent-history" id="sent-history" aria-label="Recent sent symbols"></ol>
    </div>
</section>`;
    }
}

customElements.define("copy-sent", CopySent);
