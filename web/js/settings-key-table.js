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
