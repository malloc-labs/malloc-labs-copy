// Settings page — Back up buttons for the Koch and Key record
// directories.
//
// Manual, user-initiated only. Hits /api/backup?kind=... which streams
// a zip back with an attachment Content-Disposition; the browser
// handles the download UI and the learner chooses where the file
// lives. No engine-side backup directory, no retention policy, no
// scheduler — see the discussion at the time this was added for the
// rationale (engine is a foreground process, OS-level cron/launchd
// can call a CLI if someone wants automation later).
//
// The button briefly shows "Preparing…" while the request is in
// flight so the click does not feel silent. Errors flip the label to
// "Backup failed" and surface a console message; failures are quiet
// in the UI because the only ways this can break are config-file
// problems the Settings page will surface elsewhere.

const buttons = document.querySelectorAll(".settings-backup-btn");

function downloadFromBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Revoke after a tick so Safari has time to start the download
    // before the URL goes away.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function filenameFromHeaders(headers, fallback) {
    const disposition = headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    return match ? match[1] : fallback;
}

async function runBackup(button) {
    const kind = button.dataset.kind;
    if (!kind) return;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "Preparing…";
    try {
        const res = await fetch(`/api/backup?kind=${encodeURIComponent(kind)}`, {
            cache: "no-store",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        const fallback = `copy-653-${kind}-backup.zip`;
        downloadFromBlob(blob, filenameFromHeaders(res.headers, fallback));
        const count = res.headers.get("X-Copy-Backup-File-Count");
        button.textContent = count !== null ? `Saved (${count})` : "Saved";
    } catch (err) {
        console.error("backup failed", err);
        button.textContent = "Backup failed";
    } finally {
        setTimeout(() => {
            button.textContent = original;
            button.disabled = false;
        }, 1800);
    }
}

buttons.forEach((button) => {
    button.addEventListener("click", () => runBackup(button));
});
