// <copy-rhythm-review> — collapsible rhythm-review panel shared by
// /key/ pages. Light DOM (no shadow) so core.css / copy-653.css apply
// unchanged. IDs are preserved.
//
// Attributes (page authors set the context-appropriate strings; no
// defaults so missing attributes are visibly broken):
//   meta           — empty-state text inside the timeline-meta span
//                    (e.g. "no symbols" / "no input")
//   tabs-label     — aria-label for the tabs container
//   symbols-label  — aria-label for the symbols container
//
// Load order: this module must precede key-timing.js so element IDs
// exist before scripts query them.

class CopyRhythmReview extends HTMLElement {
    connectedCallback() {
        if (this._hydrated) return;
        this._hydrated = true;
        const meta = this.getAttribute("meta") ?? "";
        const tabsLabel = this.getAttribute("tabs-label") ?? "";
        const symbolsLabel = this.getAttribute("symbols-label") ?? "";
        this.innerHTML = `
<section class="key-rhythm-review" aria-label="Rhythm review">
    <button type="button" class="timeline-toggle key-rhythm-review__toggle" id="key-rhythm-review-toggle" aria-expanded="false" aria-controls="key-rhythm-review-body">
        <span class="key-rhythm-review__label" id="key-rhythm-review-label"></span>
        <span class="timeline-arrow" id="key-rhythm-review-arrow" aria-hidden="true">▶</span>
        <span class="timeline-meta" id="key-rhythm-review-meta">${meta}</span>
    </button>
    <div class="timeline-body key-rhythm-review__body" id="key-rhythm-review-body" hidden>
        <div class="key-rhythm-review__tabs" id="key-rhythm-review-tabs" role="tablist" aria-label="${tabsLabel}"></div>
        <div class="key-rhythm-review__symbols" id="key-rhythm-review-symbols" aria-label="${symbolsLabel}"></div>
        <button type="button" class="key-rhythm-review__expand" id="key-rhythm-review-expand" hidden>Open wider view</button>
        <div class="key-rhythm-review__legend" aria-label="Perceptual timing-zone legend">
            <span><i class="key-rhythm-review__swatch key-rhythm-review__swatch--green"></i>Green Zone</span>
            <span><i class="key-rhythm-review__swatch key-rhythm-review__swatch--amber"></i>Amber Zone</span>
            <span><i class="key-rhythm-review__swatch key-rhythm-review__swatch--red"></i>Red Zone</span>
        </div>
    </div>
    <dialog class="key-rhythm-review-dialog" id="key-rhythm-review-dialog" aria-labelledby="key-rhythm-review-dialog-title">
        <div class="key-rhythm-review-dialog__bar">
            <h2 class="key-rhythm-review-dialog__title" id="key-rhythm-review-dialog-title">Rhythm review</h2>
            <button type="button" class="key-rhythm-review-dialog__close" id="key-rhythm-review-dialog-close" aria-label="Close rhythm review">Close</button>
        </div>
        <div class="key-rhythm-review-dialog__body" id="key-rhythm-review-dialog-body"></div>
        <div class="key-rhythm-review__legend key-rhythm-review-dialog__legend" aria-label="Perceptual timing-zone legend">
            <span><i class="key-rhythm-review__swatch key-rhythm-review__swatch--green"></i>Green Zone</span>
            <span><i class="key-rhythm-review__swatch key-rhythm-review__swatch--amber"></i>Amber Zone</span>
            <span><i class="key-rhythm-review__swatch key-rhythm-review__swatch--red"></i>Red Zone</span>
        </div>
    </dialog>
</section>`;
    }
}

customElements.define("copy-rhythm-review", CopyRhythmReview);
