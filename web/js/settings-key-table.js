// Settings page — saved Send Cadence sessions table.

const tbody = document.getElementById("settings-key-tbody");
const metaEl = document.getElementById("settings-key-meta");
const detailDialog = document.getElementById("settings-key-dialog");
const detailDialogTitle = document.getElementById("settings-key-dialog-title");
const detailDialogBody = document.getElementById("settings-key-dialog-body");

let openFilename = null;
const detailCache = new Map();

function formatStartedAt(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso || "-";
    return d.toLocaleString();
}

function formatDuration(startedIso, endedIso) {
    const start = new Date(startedIso).getTime();
    const end = new Date(endedIso).getTime();
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "-";
    const totalSec = Math.round((end - start) / 1000);
    const mins = Math.floor(totalSec / 60);
    const secs = totalSec % 60;
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

function appendCell(row, value) {
    const cell = document.createElement("td");
    cell.textContent = String(value);
    row.appendChild(cell);
}

function fraction(value) {
    return Number.isFinite(value) ? value.toFixed(3) : "-";
}

function buildMetaGrid(record) {
    const grid = document.createElement("dl");
    grid.className = "settings-koch-detail__meta";
    const claimed = Array.isArray(record.claimed_set) ? record.claimed_set.join(" ") : "-";
    const audio = record.audio || {};
    [
        ["Started", formatStartedAt(record.started_at)],
        ["Ended", formatStartedAt(record.ended_at)],
        ["Duration", formatDuration(record.started_at, record.ended_at)],
        ["Character speed", Number.isFinite(audio.character_speed_wpm) ? `${audio.character_speed_wpm} WPM` : "-"],
        ["Claimed set", claimed],
        ["Engine", record.engine_version ? `v${record.engine_version}` : "-"],
    ].forEach(([label, value]) => {
        const dt = document.createElement("dt");
        dt.textContent = label;
        const dd = document.createElement("dd");
        dd.textContent = value;
        grid.append(dt, dd);
    });
    return grid;
}

function buildExercisesTable(record) {
    const wrap = document.createElement("div");
    wrap.className = "settings-koch-detail__exercises";
    const heading = document.createElement("h3");
    heading.className = "settings-koch-detail__heading";
    heading.textContent = "Exercises";
    wrap.appendChild(heading);

    const table = document.createElement("table");
    table.className = "settings-koch-detail__exercises-table";
    const thead = document.createElement("thead");
    thead.innerHTML =
        "<tr><th scope=\"col\">#</th>" +
        "<th scope=\"col\">Target</th>" +
        "<th scope=\"col\">Band</th>" +
        "<th scope=\"col\">Burden</th>" +
        "<th scope=\"col\">Attempts</th>" +
        "<th scope=\"col\">Symbols</th>" +
        "<th scope=\"col\">Spacing</th>" +
        "<th scope=\"col\">Formation</th>" +
        "<th scope=\"col\">Decode</th>" +
        "<th scope=\"col\">State</th>" +
        "<th scope=\"col\">Gear</th></tr>";
    table.appendChild(thead);

    const body = document.createElement("tbody");
    const exercises = Array.isArray(record.exercises) ? record.exercises : [];
    exercises.forEach((exercise, idx) => {
        const analysis = exercise.analysis || {};
        const row = document.createElement("tr");
        appendCell(row, exercise.index || idx + 1);
        appendCell(row, exercise.target || "-");
        appendCell(row, exercise.burden_band ?? "-");
        appendCell(row, exercise.burden_score ?? "-");
        appendCell(row, analysis.attempt_count ?? 0);
        appendCell(row, fraction(analysis.symbol_fraction));
        appendCell(row, fraction(analysis.spacing_fraction));
        appendCell(row, fraction(analysis.formation_fraction));
        appendCell(row, fraction(analysis.decode_health));
        appendCell(row, analysis.band_state || "-");
        appendCell(row, exercise.gear ?? analysis.gear ?? "-");
        body.appendChild(row);
    });
    table.appendChild(body);
    wrap.appendChild(table);
    return wrap;
}

function renderDetail(record) {
    detailDialogBody.replaceChildren();
    detailDialogBody.appendChild(buildMetaGrid(record));
    detailDialogBody.appendChild(buildExercisesTable(record));
}

async function loadRecord(filename) {
    if (detailCache.has(filename)) return detailCache.get(filename);
    const res = await fetch(`/api/cadence-send?file=${encodeURIComponent(filename)}`, {
        cache: "no-store",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    detailCache.set(filename, data);
    return data;
}

function clearOpenDetail() {
    if (!openFilename) return;
    const prevRow = tbody.querySelector(`tr[data-filename="${CSS.escape(openFilename)}"]`);
    if (prevRow) {
        prevRow.dataset.expanded = "false";
        prevRow.setAttribute("aria-expanded", "false");
    }
    openFilename = null;
}

async function openDetail(filename, row) {
    clearOpenDetail();
    openFilename = filename;
    row.dataset.expanded = "true";
    row.setAttribute("aria-expanded", "true");
    detailDialogTitle.textContent = "Send session";
    detailDialogBody.textContent = "Loading send session...";
    if (!detailDialog.open) detailDialog.showModal();
    try {
        const record = await loadRecord(filename);
        if (openFilename !== filename) return;
        detailDialogTitle.textContent = formatStartedAt(record.started_at);
        renderDetail(record);
    } catch (err) {
        detailDialogBody.textContent = `Could not load send session: ${err.message}`;
    }
}

function attachRowHandler(row, filename) {
    row.classList.add("settings-koch-row");
    row.dataset.filename = filename;
    row.dataset.expanded = "false";
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.setAttribute("aria-expanded", "false");
    const toggle = () => {
        if (openFilename === filename) detailDialog.close();
        else openDetail(filename, row);
    };
    row.addEventListener("click", toggle);
    row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggle();
        }
    });
}

function renderRows(records) {
    tbody.replaceChildren();
    records.forEach((rec, idx) => {
        const row = document.createElement("tr");
        appendCell(row, idx + 1);
        appendCell(row, formatStartedAt(rec.started_at));
        appendCell(row, Array.isArray(rec.claimed_set) ? rec.claimed_set.join(" ") : "-");
        appendCell(row, rec.exercise_count ?? "-");
        attachRowHandler(row, rec.filename);
        tbody.appendChild(row);
    });
}

async function loadCadenceSessions() {
    try {
        const res = await fetch("/api/cadence-sends", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const records = Array.isArray(data.records) ? data.records : [];
        if (records.length === 0) {
            metaEl.textContent = `No saved send sessions in ${data.save_directory || "save directory"}.`;
            tbody.replaceChildren();
            return;
        }
        metaEl.textContent = `${records.length} saved send session${records.length === 1 ? "" : "s"} in ${data.save_directory}`;
        renderRows(records);
    } catch (err) {
        metaEl.textContent = `Could not load saved send sessions: ${err.message}`;
        tbody.replaceChildren();
    }
}

if (tbody) loadCadenceSessions();

detailDialog.addEventListener("close", () => {
    detailDialogTitle.textContent = "Send session";
    detailDialogBody.replaceChildren();
    clearOpenDetail();
});

detailDialog.addEventListener("click", (event) => {
    if (event.target === detailDialog) detailDialog.close();
});
