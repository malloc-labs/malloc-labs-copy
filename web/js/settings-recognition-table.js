// Settings page — saved Symbol Recognition sessions table.
//
// Fetches /api/recognitions and renders one row per saved record:
// sequence number (1 = most recent), local date & time, the claimed
// set the session drew from, and the exercise count. Clicking a row
// opens a detail dialog with the per-exercise breakdown derived from
// the voice-honest `analysis` block (recognition_analysis): the truth
// symbol, what was committed (heard), the outcome, and any
// self-corrected false start.
//
// Recognition is NOT geared — there is no band/gear/state column here
// and no weighted score. The detail surfaces counts and outcomes only,
// the substrate a future gear model would divide. A silent exercise is
// neutral ("nothing heard"), neither evidence nor error. The committed
// (heard) column is voice-derived and may differ from the learner's
// editable answer by design; we show what was heard, not a reconciled
// value. Backend evidence, not a score (spec §9).

const tbody = document.getElementById("settings-recognition-tbody");
const metaEl = document.getElementById("settings-recognition-records-meta");
const detailDialog = document.getElementById("settings-recognition-dialog");
const detailDialogTitle = document.getElementById("settings-recognition-dialog-title");
const detailDialogBody = document.getElementById("settings-recognition-dialog-body");
const prevButton = document.getElementById("settings-recognition-dialog-prev");
const nextButton = document.getElementById("settings-recognition-dialog-next");
const countEl = document.getElementById("settings-recognition-dialog-count");

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

function buildMetaGrid(record) {
    const grid = document.createElement("dl");
    grid.className = "settings-koch-detail__meta";
    const audio = record.audio || {};
    const charWpm = audio.character_speed_wpm;
    const effWpm = audio.effective_speed_wpm;
    const toneHz = audio.tone_frequency_hz;
    const claimed = Array.isArray(record.claimed_set) ? record.claimed_set.join(" ") : "-";
    [
        ["Started", formatStartedAt(record.started_at)],
        ["Ended", formatStartedAt(record.ended_at)],
        ["Duration", formatDuration(record.started_at, record.ended_at)],
        ["Character speed", Number.isFinite(charWpm) ? `${charWpm} WPM` : "-"],
        ["Effective speed", Number.isFinite(effWpm) ? `${effWpm} WPM` : "-"],
        ["Tone", Number.isFinite(toneHz) ? `${toneHz} Hz` : "-"],
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
    { label: "Symbol" },
    {
        label: "Heard",
        tooltip:
            "What was committed for this symbol — the last thing said in the recognition " +
            "window. Voice-derived, so it may differ from a later edited answer.",
    },
    {
        label: "Outcome",
        tooltip:
            "correct / substitution (committed the wrong symbol) / caught-correct or " +
            "caught-substitution (a false start was superseded before committing) / miss. " +
            "A silent window reads as “nothing heard” and counts as neither evidence nor error.",
    },
    {
        label: "Self-corrected",
        tooltip:
            "False starts the learner said then superseded before committing — evidence a " +
            "discrimination is forming, kept separate from committed errors.",
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
            if (idx >= EXERCISES_COLUMNS.length - 2) {
                th.dataset.tooltipAlign = "right";
            }
        }
        tr.appendChild(th);
    });
    thead.appendChild(tr);
    return thead;
}

// Recognition exercises play one symbol per window, so an analysis
// carries at most one slot. Collapse a slot list defensively in case a
// future exercise plays more than one.
function summariseSlots(slots) {
    if (!Array.isArray(slots) || slots.length === 0) {
        return { heard: "-", outcome: "nothing heard", caught: "-" };
    }
    const heard = slots
        .map((s) => (typeof s.committed === "string" && s.committed.length ? s.committed : "·"))
        .join(" ");
    const outcome = slots.map((s) => s.outcome || "-").join(", ");
    const caughtSymbols = slots
        .flatMap((s) => (Array.isArray(s.superseded) ? s.superseded : []))
        .filter((sym) => typeof sym === "string" && sym.length);
    const caught = caughtSymbols.length ? caughtSymbols.join(" ") : "-";
    return { heard, outcome, caught };
}

function buildExercisesTable(record) {
    const wrap = document.createElement("div");
    wrap.className = "settings-koch-detail__exercises";
    const heading = document.createElement("h3");
    heading.className = "settings-koch-detail__heading";
    heading.textContent = "Exercises";
    wrap.appendChild(heading);

    const exercises = Array.isArray(record.exercises) ? record.exercises : [];
    if (exercises.length === 0) {
        const empty = document.createElement("p");
        empty.className = "settings-koch-detail__empty";
        empty.textContent = "No exercises recorded.";
        wrap.appendChild(empty);
        return wrap;
    }

    const table = document.createElement("table");
    table.className = "settings-koch-detail__exercises-table";
    table.appendChild(buildExercisesHead());

    const body = document.createElement("tbody");
    exercises.forEach((exercise, idx) => {
        const analysis = exercise.analysis || {};
        const row = document.createElement("tr");
        appendCell(row, exercise.index || idx + 1);
        appendCell(row, exercise.target || "-");
        if (analysis.has_evidence) {
            const { heard, outcome, caught } = summariseSlots(analysis.slots);
            appendCell(row, heard);
            appendCell(row, outcome);
            appendCell(row, caught);
        } else {
            appendCell(row, "-");
            appendCell(row, "nothing heard");
            appendCell(row, "-");
        }
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
    const res = await fetch(`/api/recognition?file=${encodeURIComponent(filename)}`, {
        cache: "no-store",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    detailCache.set(filename, data);
    return data;
}

async function deleteRecord(filename) {
    // GET, not POST: the websockets legacy server we ride on accepts
    // only GET; the server-side handler is method-agnostic.
    const res = await fetch(
        `/api/delete-recognition?file=${encodeURIComponent(filename)}`,
        { cache: "no-store" },
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    detailCache.delete(filename);
    if (openFilename === filename) {
        detailDialog.close();
    }
    await loadRecognitionSessions();
    window.dispatchEvent(new CustomEvent("copy-settings-records-changed", {
        detail: { kind: "recognition" },
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
    detailDialogTitle.textContent = "Recognition session";
    detailDialogBody.textContent = "Loading session...";
    updateNavButtons();
    if (!detailDialog.open) detailDialog.showModal();
    try {
        const record = await loadRecord(filename);
        if (openFilename !== filename) return;
        detailDialogTitle.textContent = formatStartedAt(record.started_at);
        renderDetail(record);
        updateNavButtons();
    } catch (err) {
        detailDialogBody.textContent = `Could not load session: ${err.message}`;
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
    button.setAttribute("aria-label", "Delete recognition session record");
    button.addEventListener("click", async (event) => {
        event.stopPropagation();
        const ok = window.confirm("Delete this recognition session record?");
        if (!ok) return;
        try {
            button.disabled = true;
            await deleteRecord(filename);
        } catch (err) {
            button.disabled = false;
            window.alert(`Could not delete recognition session: ${err.message}`);
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

async function loadRecognitionSessions() {
    try {
        const res = await fetch("/api/recognitions", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const records = Array.isArray(data.records) ? data.records : [];
        if (records.length === 0) {
            metaEl.textContent = `No saved recognition sessions in ${data.save_directory || "save directory"}.`;
            currentRecords = [];
            openFilename = null;
            updateNavButtons();
            tbody.replaceChildren();
            return;
        }
        metaEl.textContent = `${records.length} saved session${records.length === 1 ? "" : "s"} in ${data.save_directory}`;
        renderRows(records);
    } catch (err) {
        metaEl.textContent = `Could not load saved recognition sessions: ${err.message}`;
        currentRecords = [];
        openFilename = null;
        updateNavButtons();
        tbody.replaceChildren();
    }
}

if (tbody) loadRecognitionSessions();

detailDialog.addEventListener("close", () => {
    detailDialogTitle.textContent = "Recognition session";
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
