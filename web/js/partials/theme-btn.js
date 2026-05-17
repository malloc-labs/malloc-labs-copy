// <copy-theme-btn> — theme toggle button shared by every landing-
// shell page. Light DOM (no shadow) so core.css applies unchanged.
// Identical on every host page today, so no attributes.
//
// Load order: this module must run before DOMContentLoaded fires,
// because theme.js (in <head>) binds to #theme-toggle from a
// DOMContentLoaded handler. End-of-body module scripts execute
// after parse and before DOMContentLoaded, so the default
// placement already satisfies this. theme.js will also overwrite
// the button's textContent ("light"/"dark") to match the stored
// theme, so the static label here is just an initial paint.

class CopyThemeBtn extends HTMLElement {
    connectedCallback() {
        if (this._hydrated) return;
        this._hydrated = true;
        this.innerHTML = `<button class="theme-btn" id="theme-toggle" aria-label="Switch theme">light</button>`;
    }
}

customElements.define("copy-theme-btn", CopyThemeBtn);
