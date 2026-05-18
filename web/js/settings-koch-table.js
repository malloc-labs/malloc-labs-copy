// Settings page — saved Koch sessions table.
//
// Fetches /api/koch-exercises and renders one row per saved record:
// sequence number (1 = most recent), local date & time, and the
// claimed set the session was drawn from. The server reads the
// configured save_directory fresh on each request, so a learner who
// edits config.toml sees the new directory's contents on reload.

const tbody = document.getElementById("settings-koch-tbody");
const metaEl = document.getElementById("settings-koch-meta");

function formatStartedAt(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
}

function renderRows(records) {
    tbody.replaceChildren();
    records.forEach((rec, idx) => {
        const tr = document.createElement("tr");

        const numCell = document.createElement("td");
        numCell.textContent = String(idx + 1);
        tr.appendChild(numCell);

        const timeCell = document.createElement("td");
        timeCell.textContent = formatStartedAt(rec.started_at);
        tr.appendChild(timeCell);

        const claimedCell = document.createElement("td");
        claimedCell.textContent = rec.claimed_set.join(" ");
        tr.appendChild(claimedCell);

        tbody.appendChild(tr);
    });
}

async function loadKochSessions() {
    try {
        const res = await fetch("/api/koch-exercises", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const records = Array.isArray(data.records) ? data.records : [];
        if (records.length === 0) {
            metaEl.textContent = `No saved Koch sessions in ${data.save_directory || "save directory"}.`;
            tbody.replaceChildren();
            return;
        }
        metaEl.textContent = `${records.length} saved session${records.length === 1 ? "" : "s"} in ${data.save_directory}`;
        renderRows(records);
    } catch (err) {
        metaEl.textContent = `Could not load saved sessions: ${err.message}`;
        tbody.replaceChildren();
    }
}

loadKochSessions();
