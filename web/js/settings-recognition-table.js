// Settings page — saved Symbol Recognition sessions table.
//
// Fetches /api/recognitions and renders one row per saved record:
// sequence number (1 = most recent), local date & time, the claimed
// set the session drew from, and the exercise count. Clicking a row
// opens a detail dialog with an exercise-level summary derived from
// the voice-honest `analysis` block (recognition_analysis): what was
// played, what Vosk heard, what the learner committed after review,
// per-exercise outcome counts, and the two confusion streams.
//
// Recognition has no state or gear model yet. Those columns are shown
// as reserved placeholders so the table shape can match the other
// Settings record dialogs without inventing backend semantics. A silent
// exercise is neutral ("nothing heard"), neither evidence nor error.
// The Heard column is voice-derived and may differ from the learner's
// editable Answer by design. Backend evidence, not a score (spec §9).

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
    { label: "Played" },
    {
        label: "Heard",
        tooltip:
            "What was committed for this exercise — the last thing said in each recognition " +
            "window. Voice-derived, so it may differ from a later edited answer.",
    },
    {
        label: "Answer",
        tooltip:
            "What the learner saved after the session. This can differ from Heard when " +
            "the recogniser transcript was edited before saving.",
    },
    {
        label: "Correct",
        tooltip:
            "Correct recognition windows over total windows in this exercise. Caught " +
            "corrections are counted separately, not as plain correct.",
    },
    {
        label: "Subst.",
        tooltip: "Committed substitutions — windows where the final heard symbol was wrong.",
    },
    {
        label: "Caught",
        tooltip:
            "Self-corrections — false starts superseded before the final committed symbol.",
    },
    {
        label: "Miss",
        tooltip: "Windows where no symbol was heard.",
    },
    {
        label: "Confusions",
        tooltip:
            "Committed confusions and caught false starts, kept separate. 'caught' means " +
            "the learner superseded the false start before committing.",
    },
    {
        label: "State",
        tooltip:
            "Reserved for a future Recognition state model. Recognition does not define " +
            "state yet, so current records show a dash.",
    },
    {
        label: "Gear",
        tooltip:
            "Reserved for a future Recognition gear model. Recognition does not define " +
            "gears yet, so current records show a dash.",
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
            if (idx >= EXERCISES_COLUMNS.length - 3) {
                th.dataset.tooltipAlign = "right";
            }
        }
        tr.appendChild(th);
    });
    thead.appendChild(tr);
    return thead;
}

function formatSymbolSequence(value) {
    if (typeof value !== "string" || value.length === 0) return "-";
    const trimmed = value.trim();
    if (!trimmed) return "-";
    if (/\s/.test(trimmed)) return trimmed.replace(/\s+/g, " ");
    return Array.from(trimmed).join(" ");
}

function countsForExercise(analysis) {
    const counts = analysis && typeof analysis === "object" ? analysis.counts || {} : {};
    const correct = finiteCount(counts.correct);
    const substitution = finiteCount(counts.substitution);
    const caughtCorrect = finiteCount(counts.caught_correct);
    const caughtSubstitution = finiteCount(counts.caught_substitution);
    const miss = finiteCount(counts.miss);
    const caught = caughtCorrect + caughtSubstitution;
    const total = correct + substitution + caught + miss;
    return { correct, substitution, caught, miss, total };
}

function finiteCount(value) {
    return Number.isFinite(value) ? value : 0;
}

function countPairKey(pair) {
    if (!Array.isArray(pair) || pair.length !== 2) return null;
    const [target, heard] = pair;
    if (typeof target !== "string" || typeof heard !== "string") return null;
    if (!target || !heard) return null;
    return `${target}->${heard}`;
}

function summarisePairs(pairs) {
    const tallies = new Map();
    if (Array.isArray(pairs)) {
        pairs.forEach((pair) => {
            const key = countPairKey(pair);
            if (key) tallies.set(key, (tallies.get(key) || 0) + 1);
        });
    }
    return Array.from(tallies.entries()).map(([key, count]) =>
        count > 1 ? `${key} x${count}` : key,
    );
}

function summariseConfusions(analysis) {
    if (!analysis || typeof analysis !== "object") return "-";
    const committed = summarisePairs(analysis.committed_confusions);
    const caught = summarisePairs(analysis.caught_confusions).map((item) => `caught ${item}`);
    const parts = committed.concat(caught);
    if (analysis.ambiguous_lag === true) parts.push("lag?");
    return parts.length ? parts.join(", ") : "-";
}

function recognitionState(exercise) {
    return exercise?.analysis?.recognition_state || "-";
}

function recognitionGear(exercise) {
    const gear = exercise?.analysis?.recognition_gear ?? exercise?.recognition_gear;
    return Number.isFinite(gear) ? gear : "-";
}

function buildSummaryRow(exercises) {
    const analysed = exercises.filter((exercise) => exercise?.analysis?.has_evidence === true);
    if (analysed.length === 0) return null;

    let correct = 0;
    let substitution = 0;
    let caught = 0;
    let miss = 0;
    let total = 0;

    analysed.forEach((exercise) => {
        const counts = countsForExercise(exercise.analysis);
        correct += counts.correct;
        substitution += counts.substitution;
        caught += counts.caught;
        miss += counts.miss;
        total += counts.total;
    });

    const row = document.createElement("tr");
    row.className = "settings-koch-detail__exercises-summary";
    appendCell(row, "Σ");
    appendCell(row, "");
    appendCell(row, "");
    appendCell(row, "");
    appendCell(row, total > 0 ? `${correct}/${total}` : "-");
    appendCell(row, substitution);
    appendCell(row, caught);
    appendCell(row, miss);
    appendCell(row, "");
    appendCell(row, "");
    appendCell(row, "");
    return row;
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
    table.classList.add("settings-recognition-detail__exercises-table");
    table.appendChild(buildExercisesHead());

    const body = document.createElement("tbody");
    exercises.forEach((exercise, idx) => {
        const analysis = exercise.analysis || {};
        const counts = countsForExercise(analysis);
        const row = document.createElement("tr");
        appendCell(row, exercise.index || idx + 1);
        appendCell(row, formatSymbolSequence(exercise.target));
        appendCell(row, formatSymbolSequence(analysis.committed_answer));
        appendCell(row, formatSymbolSequence(exercise.answer));
        if (analysis.has_evidence) {
            appendCell(row, counts.total > 0 ? `${counts.correct}/${counts.total}` : "-");
            appendCell(row, counts.substitution);
            appendCell(row, counts.caught);
            appendCell(row, counts.miss);
            appendCell(row, summariseConfusions(analysis));
        } else {
            appendCell(row, "-");
            appendCell(row, "-");
            appendCell(row, "-");
            appendCell(row, "-");
            appendCell(row, "-");
        }
        appendCell(row, recognitionState(exercise));
        appendCell(row, recognitionGear(exercise));
        body.appendChild(row);
    });
    table.appendChild(body);
    const summary = buildSummaryRow(exercises);
    if (summary) {
        const tfoot = document.createElement("tfoot");
        tfoot.appendChild(summary);
        table.appendChild(tfoot);
    }
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
