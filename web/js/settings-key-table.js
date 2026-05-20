// Settings page — saved Send Cadence sessions table.

const tbody = document.getElementById("settings-key-tbody");
const metaEl = document.getElementById("settings-key-meta");
const detailDialog = document.getElementById("settings-key-dialog");
const detailDialogTitle = document.getElementById("settings-key-dialog-title");
const detailDialogBody = document.getElementById("settings-key-dialog-body");
const prevButton = document.getElementById("settings-key-dialog-prev");
const nextButton = document.getElementById("settings-key-dialog-next");
const countEl = document.getElementById("settings-key-dialog-count");

let openFilename = null;
let currentRecords = [];
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

const EXERCISES_COLUMNS = [
    { label: "#" },
    { label: "Target" },
    {
        label: "Band",
        tooltip:
            "Burden band — which slice of the curriculum this exercise sits in. " +
            "Band 1 is the simplest; later bands rise as targets get longer or more demanding.",
    },
    {
        label: "Burden",
        tooltip:
            "Burden score — a length-and-difficulty number for the target. Higher means a heavier " +
            "exercise to send cleanly.",
    },
    {
        label: "Attempts",
        tooltip:
            "How many sending attempts you made on this target. The scored row picks your best " +
            "attempt; the others are kept on the record but not double-counted.",
    },
    {
        label: "Symbols",
        tooltip:
            "Symbol accuracy — decoded characters vs target (edit-distance based). " +
            "Contributes 40% of the combined fraction.",
    },
    {
        label: "Spacing",
        tooltip:
            "Spacing accuracy — word boundaries placed correctly between decoded symbols. " +
            "Contributes 30% of the combined fraction.",
    },
    {
        label: "Formation",
        tooltip:
            "Formation quality — how cleanly your dits, dahs, and element gaps matched the " +
            "expected timing for each character. Contributes 20% of the combined fraction.",
    },
    {
        label: "Gap",
        tooltip:
            "Gap-timing readability — were your inter-element, inter-symbol, and inter-word gaps " +
            "in the readable range. Contributes 5% of the combined fraction.",
    },
    {
        label: "Decode",
        tooltip:
            "Decode health — fraction of keyed events that resolved to a real symbol rather than " +
            "an unresolvable “?”. Contributes 5% of the combined fraction.",
    },
    {
        label: "Combined",
        tooltip:
            "Combined fraction — weighted total: 0.40 Symbols + 0.30 Spacing + 0.20 Formation + " +
            "0.05 Gap + 0.05 Decode.",
    },
    {
        label: "State",
        tooltip:
            "Band state from the combined fraction: low (<0.70), building (<0.85), " +
            "steady (<0.95), strong (<1.0), exact (=1.0).",
    },
    {
        label: "Gear",
        tooltip:
            "Curriculum pacing gear the band was on for this exercise. Strong runs nudge it up; " +
            "struggles nudge it down.",
    },
];

function buildExercisesHead() {
    const thead = document.createElement("thead");
    const tr = document.createElement("tr");
    EXERCISES_COLUMNS.forEach((col, idx) => {
        const th = document.createElement("th");
        th.scope = "col";
        th.textContent = col.label;
        if (col.tooltip) {
            th.dataset.tooltip = col.tooltip;
            th.tabIndex = 0;
            // Right-edge columns flip the tooltip so it does not clip
            // against the table / dialog right edge.
            if (idx >= EXERCISES_COLUMNS.length - 2) {
                th.dataset.tooltipAlign = "right";
            }
        }
        tr.appendChild(th);
    });
    thead.appendChild(tr);
    return thead;
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
    table.appendChild(buildExercisesHead());

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
        appendCell(row, fraction(analysis.gap_timing_fraction));
        appendCell(row, fraction(analysis.decode_health));
        appendCell(row, fraction(analysis.combined_fraction));
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

async function deleteRecord(filename) {
    const res = await fetch(
        `/api/delete-cadence-send?file=${encodeURIComponent(filename)}`,
        { method: "POST", cache: "no-store" },
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    detailCache.delete(filename);
    if (openFilename === filename) {
        detailDialog.close();
    }
    await loadCadenceSessions();
    window.dispatchEvent(new CustomEvent("copy-settings-records-changed", {
        detail: { kind: "key" },
    }));
}

function clearOpenDetail() {
    if (!openFilename) return;
    const prevRow = rowForFilename(openFilename);
    if (prevRow) {
        prevRow.dataset.expanded = "false";
        prevRow.setAttribute("aria-expanded", "false");
    }
    openFilename = null;
}

function rowForFilename(filename) {
    return tbody.querySelector(`tr[data-filename="${cssEscape(filename)}"]`);
}

function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(value);
    }
    return value.replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function openRecordByOffset(offset) {
    if (!openFilename || offset === 0) return;
    const idx = currentRecords.findIndex((rec) => rec.filename === openFilename);
    const nextRecord = currentRecords[idx + offset];
    if (!nextRecord) return;
    const row = rowForFilename(nextRecord.filename);
    if (row) {
        openDetail(nextRecord.filename, row);
    }
}

function updateNavButtons() {
    const idx = currentRecords.findIndex((rec) => rec.filename === openFilename);
    const hasOpenRecord = idx >= 0;
    if (prevButton) prevButton.disabled = !hasOpenRecord || idx === 0;
    if (nextButton) nextButton.disabled = !hasOpenRecord || idx === currentRecords.length - 1;
    if (countEl) {
        countEl.textContent = hasOpenRecord
            ? `${idx + 1} of ${currentRecords.length}`
            : `0 of ${currentRecords.length}`;
    }
}

async function openDetail(filename, row) {
    clearOpenDetail();
    openFilename = filename;
    row.dataset.expanded = "true";
    row.setAttribute("aria-expanded", "true");
    detailDialogTitle.textContent = "Send session";
    detailDialogBody.textContent = "Loading send session...";
    updateNavButtons();
    if (!detailDialog.open) detailDialog.showModal();
    try {
        const record = await loadRecord(filename);
        if (openFilename !== filename) return;
        detailDialogTitle.textContent = formatStartedAt(record.started_at);
        renderDetail(record);
        updateNavButtons();
    } catch (err) {
        detailDialogBody.textContent = `Could not load send session: ${err.message}`;
        updateNavButtons();
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

function appendDeleteCell(row, filename) {
    const cell = document.createElement("td");
    cell.className = "settings-koch-table__delete-cell";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "settings-koch-table__delete";
    button.textContent = "Delete";
    button.setAttribute("aria-label", "Delete Key send session record");
    button.addEventListener("click", async (event) => {
        event.stopPropagation();
        const ok = window.confirm("Delete this Key send session record?");
        if (!ok) return;
        try {
            button.disabled = true;
            await deleteRecord(filename);
        } catch (err) {
            button.disabled = false;
            window.alert(`Could not delete Key send session: ${err.message}`);
        }
    });
    button.addEventListener("keydown", (event) => {
        event.stopPropagation();
    });
    cell.appendChild(button);
    row.appendChild(cell);
}

function renderRows(records) {
    tbody.replaceChildren();
    currentRecords = records;
    openFilename = null;
    updateNavButtons();
    records.forEach((rec, idx) => {
        const row = document.createElement("tr");
        appendCell(row, idx + 1);
        appendCell(row, formatStartedAt(rec.started_at));
        appendCell(row, Array.isArray(rec.claimed_set) ? rec.claimed_set.join(" ") : "-");
        appendCell(row, rec.exercise_count ?? "-");
        appendDeleteCell(row, rec.filename);
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
            currentRecords = [];
            openFilename = null;
            updateNavButtons();
            tbody.replaceChildren();
            return;
        }
        metaEl.textContent = `${records.length} saved send session${records.length === 1 ? "" : "s"} in ${data.save_directory}`;
        renderRows(records);
    } catch (err) {
        metaEl.textContent = `Could not load saved send sessions: ${err.message}`;
        currentRecords = [];
        openFilename = null;
        updateNavButtons();
        tbody.replaceChildren();
    }
}

if (tbody) loadCadenceSessions();

detailDialog.addEventListener("close", () => {
    detailDialogTitle.textContent = "Send session";
    detailDialogBody.replaceChildren();
    clearOpenDetail();
    updateNavButtons();
});

detailDialog.addEventListener("click", (event) => {
    if (event.target === detailDialog) detailDialog.close();
});

prevButton?.addEventListener("click", () => openRecordByOffset(-1));
nextButton?.addEventListener("click", () => openRecordByOffset(1));

document.addEventListener("keydown", (event) => {
    if (!detailDialog.open || event.altKey || event.ctrlKey || event.metaKey) return;
    const key = event.key.toLowerCase();
    if (event.key === "ArrowLeft" || event.key === "<" || key === "h") {
        event.preventDefault();
        openRecordByOffset(-1);
    } else if (event.key === "ArrowRight" || event.key === ">" || key === "l") {
        event.preventDefault();
        openRecordByOffset(1);
    }
});
