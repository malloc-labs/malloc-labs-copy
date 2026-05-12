// Render the running Copy package version in the static footer.
//
// The value comes from the Python server so the browser reflects the installed
// package version without a frontend build step.

async function renderAppVersion() {
    const versionEl = document.querySelector("[data-app-version]");
    if (!versionEl) return;

    try {
        const response = await fetch("/api/version", { cache: "no-store" });
        if (!response.ok) return;

        const payload = await response.json();
        if (typeof payload.version !== "string" || !payload.version.trim()) return;

        versionEl.textContent = `v${payload.version}`;
        versionEl.hidden = false;
    } catch {
        versionEl.hidden = true;
    }
}

renderAppVersion();
