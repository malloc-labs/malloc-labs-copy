// <copy-koch-sequence> — the Koch-sequence panel: an aria-labelled
// section wrapping a row of symbol tokens, with either a static
// label or a collapsible toggle header above the row. Light DOM
// (no shadow) so core.css / copy-653.css apply unchanged.
//
// Attributes:
//   section-label  — text for the section's aria-label (e.g.
//                    "Known symbol sequence", "Focus symbols")
//   row-id         — id on the inner sequence-row div; defaults to
//                    "sequence-row". Word-detection overrides to
//                    "focus-row" so its JS can target the right row.
//   label          — text for the static-label <p>; defaults to
//                    "Sequence". Ignored when collapsible is set.
//   collapsible    — boolean; render the toggle-button header
//                    (#sequence-toggle) and start the row hidden.
//   read-only      — boolean; add the sequence-row--read-only
//                    modifier and render <span> tokens instead of
//                    <button>. /key/ pages set this; Koch pages
//                    (where users claim symbols) do not.
//
// Load order: this module must precede scripts that touch the
// sequence-row id or #sequence-toggle.

// Canonical Koch order — mirrors KOCH_ORDER in patterns.py.
export const KOCH_ORDER = [
    "K", "M", "U", "R", "E", "S", "N", "A", "P", "T",
    "L", "W", "I", ".", "J", "Z", "=", "F", "O", "Y",
    ",", "V", "G", "5", "/", "Q", "9", "2", "H", "3",
    "8", "B", "?", "4", "7", "C", "1", "D", "6", "0", "X",
];

const toggleHeader = (rowId) => `<button type="button" class="koch-sequence__toggle" id="sequence-toggle" aria-expanded="false" aria-controls="${rowId}">
        <span class="koch-sequence__label" id="sequence-toggle-label"></span>
        <span class="koch-sequence__arrow" id="sequence-arrow" aria-hidden="true">▶</span>
    </button>`;

const staticHeader = (label) => `<p class="sequence-label">${label}</p>`;

class CopyKochSequence extends HTMLElement {
    connectedCallback() {
        if (this._hydrated) return;
        this._hydrated = true;
        const sectionLabel = this.getAttribute("section-label") ?? "";
        const rowId = this.getAttribute("row-id") ?? "sequence-row";
        const label = this.getAttribute("label") ?? "Sequence";
        const collapsible = this.hasAttribute("collapsible");
        const readOnly = this.hasAttribute("read-only");
        const header = collapsible ? toggleHeader(rowId) : staticHeader(label);
        const rowClasses = readOnly ? "sequence-row sequence-row--read-only" : "sequence-row";
        const hiddenAttr = collapsible ? " hidden" : "";
        this.innerHTML = `
<section class="koch-sequence" aria-label="${sectionLabel}">
    ${header}
    <div class="${rowClasses}" id="${rowId}" role="list"${hiddenAttr}></div>
</section>`;
        const row = this.querySelector(`#${CSS.escape(rowId)}`);
        const tag = readOnly ? "span" : "button";
        KOCH_ORDER.forEach((sym) => {
            const token = document.createElement(tag);
            if (tag === "button") token.type = "button";
            token.textContent = sym;
            token.dataset.symbol = sym;
            token.dataset.state = "available";
            token.setAttribute("role", "listitem");
            token.classList.add("seq-token");
            row.appendChild(token);
        });
    }
}

customElements.define("copy-koch-sequence", CopyKochSequence);
