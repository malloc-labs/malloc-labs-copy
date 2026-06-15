// <copy-top-menu> — collapsible top-menu shared by /key/ pages.
// Light DOM (no shadow) so core.css / copy-653.css apply unchanged.
//
// Attributes:
//   show-new — also render the "new" button (#key-new-set). Cadence
//              uses it to start a fresh exercise set; Freeplay does
//              not have that concept and omits the attribute.
//   hide-clear — omit the "clear" button. Training has no sent-history
//                surface yet, but still uses the sound control.
//
// Load order: this module must precede key-timing.js so the buttons
// exist before handlers bind to them.

class CopyTopMenu extends HTMLElement {
    connectedCallback() {
        if (this._hydrated) return;
        this._hydrated = true;
        const showNew = this.hasAttribute("show-new");
        const showClear = !this.hasAttribute("hide-clear");
        this.innerHTML = `
<section class="key-page-actions" aria-label="Top menu">
    <button type="button" class="key-page-actions__toggle" id="key-page-actions-toggle" aria-expanded="false" aria-controls="key-page-actions-items">
        <span class="key-page-actions__label" id="key-page-actions-label"></span>
        <span class="key-page-actions__arrow" id="key-page-actions-arrow" aria-hidden="true">▶</span>
    </button>
    <div class="key-page-actions__items" id="key-page-actions-items" hidden>
        <button type="button" class="key-sound-toggle" id="key-sound-toggle">enable sound</button>
        ${showClear ? '<button type="button" class="key-sound-toggle" id="key-clear-sent">clear</button>' : ""}
        ${showNew ? '<button type="button" class="key-sound-toggle" id="key-new-set">new</button>' : ""}
    </div>
</section>`;
    }
}

customElements.define("copy-top-menu", CopyTopMenu);
