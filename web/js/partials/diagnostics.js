// <copy-diagnostics> — developer-only diagnostics panel shared by the
// /key/ pages. Light DOM (no shadow) so core.css / copy-653.css apply
// unchanged. IDs are preserved, so anything binding to #diag-input,
// #diag-log, etc. works without awaiting a custom event.
//
// Load order matters: this module must precede key-timing.js so the
// element is upgraded (and its inner DOM populated) before scripts
// query the diagnostics IDs.

const TEMPLATE = `
<section class="key-diagnostics developer-only" aria-label="Key diagnostics">
    <div class="key-diagnostics__header">
        <p class="sequence-label">Diagnostics</p>
        <div class="key-diagnostics-actions">
            <button type="button" class="key-sound-toggle" id="copy-diagnostics">copy diagnostics</button>
            <button type="button" class="key-sound-toggle" id="key-input-toggle">input armed</button>
        </div>
    </div>
    <dl class="key-diagnostics-grid">
        <div><dt>MIDI input</dt><dd id="diag-input">—</dd></div>
        <div><dt>Audio</dt><dd id="diag-audio">waiting</dd></div>
        <div><dt>Last event</dt><dd id="diag-event">—</dd></div>
        <div><dt>Last raw MIDI</dt><dd id="diag-raw">—</dd></div>
        <div><dt>Last element</dt><dd id="diag-element">—</dd></div>
        <div><dt>Last gap</dt><dd id="diag-gap">—</dd></div>
        <div><dt>Timing</dt><dd id="diag-timing">—</dd></div>
    </dl>
    <div class="key-diagnostics-table-wrap">
        <table class="key-diagnostics-table">
            <caption>Raw MIDI</caption>
            <thead><tr>
                <th scope="col">Timestamp</th>
                <th scope="col">Event</th>
                <th scope="col">Action</th>
                <th scope="col">Focus</th>
            </tr></thead>
            <tbody id="diag-raw-log"></tbody>
        </table>
    </div>
    <div class="key-diagnostics-table-wrap">
        <table class="key-diagnostics-table">
            <caption>Decoded symbols</caption>
            <thead><tr>
                <th scope="col">Timestamp</th>
                <th scope="col">Raw on</th>
                <th scope="col">Generated on</th>
                <th scope="col">Symbol</th>
                <th scope="col">Morse</th>
            </tr></thead>
            <tbody id="diag-log"></tbody>
        </table>
    </div>
</section>`;

class CopyDiagnostics extends HTMLElement {
    connectedCallback() {
        if (this._hydrated) return;
        this._hydrated = true;
        this.innerHTML = TEMPLATE;
    }
}

customElements.define("copy-diagnostics", CopyDiagnostics);
