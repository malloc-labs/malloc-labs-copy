// Settings page — saved Koch sessions table.
//
// Fetches /api/koch-exercises and renders one row per saved record:
// sequence number (1 = most recent), local date & time, and the
// claimed set the session was drawn from. The server reads the
// configured save_directory fresh on each request, so a learner who
// edits config.toml sees the new directory's contents on reload.
//
// Each row is clickable. Clicking expands an inline detail panel
// beneath it that fetches the full record on demand and shows the
// session's metadata, audio snapshot, and a per-exercise comparison
// of what was played versus what the learner typed. Only one detail
// panel is open at a time — opening another row closes the first.

const tbody = document.getElementById("settings-koch-tbody");
const metaEl = document.getElementById("settings-koch-meta");
const detailDialog = document.getElementById("settings-koch-dialog");
const detailDialogTitle = document.getElementById("settings-koch-dialog-title");
const detailDialogBody = document.getElementById("settings-koch-dialog-body");
const prevButton = document.getElementById("settings-koch-dialog-prev");
const nextButton = document.getElementById("settings-koch-dialog-next");
const countEl = document.getElementById("settings-koch-dialog-count");

let openFilename = null;
let currentRecords = [];
const detailCache = new Map();

function formatStartedAt(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
}

function formatDuration(startedIso, endedIso) {
    const start = new Date(startedIso).getTime();
    const end = new Date(endedIso).getTime();
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "—";
    const totalSec = Math.round((end - start) / 1000);
    const mins = Math.floor(totalSec / 60);
    const secs = totalSec % 60;
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

function buildMetaPairs(record) {
    const audio = record.audio || {};
    const charWpm = audio.character_speed_wpm;
    const effWpm = audio.effective_speed_wpm;
    const toneHz = audio.tone_frequency_hz;
    const farnsworth = Number.isFinite(charWpm) && Number.isFinite(effWpm) && effWpm < charWpm;
    const claimed = Array.isArray(record.claimed_set) ? record.claimed_set.join(" ") : "—";

    const pairs = [
        ["Started", formatStartedAt(record.started_at)],
        ["Ended", formatStartedAt(record.ended_at)],
        ["Duration", formatDuration(record.started_at, record.ended_at)],
        ["Character speed", Number.isFinite(charWpm) ? `${charWpm} WPM` : "—"],
        ["Effective speed", Number.isFinite(effWpm) ? `${effWpm} WPM` : "—"],
        ["Farnsworth", farnsworth ? "on" : "off"],
        ["Tone", Number.isFinite(toneHz) ? `${toneHz} Hz` : "—"],
        ["Claimed set", claimed],
    ];
    if (record.engine_version) pairs.push(["Engine", `v${record.engine_version}`]);
    return pairs;
}

function buildMetaGrid(record) {
    const grid = document.createElement("dl");
    grid.className = "settings-koch-detail__meta";
    buildMetaPairs(record).forEach(([label, value]) => {
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
    { label: "You typed" },
    {
        label: "Band",
        tooltip:
            "Burden band — which slice of the Koch curriculum this exercise sits in. " +
            "Band 1 is the simplest; later bands rise as the played material gets longer or more demanding.",
    },
    {
        label: "Burden",
        tooltip:
            "Burden score — a length-and-difficulty number for what was played " +
            "(the fixed DE anchor is excluded). Higher means a heavier exercise.",
    },
    {
        label: "Symbols",
        tooltip:
            "Symbol accuracy — characters you got right (correct / available), " +
            "with spaces ignored. Edit-distance based, so insertions and missed letters both count.",
    },
    {
        label: "Spacing",
        tooltip:
            "Spacing accuracy — word boundaries you placed correctly (correct / available). " +
            "Tracks where your spaces landed, separately from the letters.",
    },
    {
        label: "Repeat",
        tooltip:
            "Repeat weight — discount applied when the same core already came up earlier " +
            "in the session. 1.0 first time, then 0.7 / 0.5 / 0.35 on later repeats.",
    },
    {
        label: "Evidence",
        tooltip:
            "Evidence score — symbol and spacing accuracy combined, then weighted by burden, " +
            "position in the session, and the repeat weight.",
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

function buildExercisesList(record) {
    const wrap = document.createElement("div");
    wrap.className = "settings-koch-detail__exercises";

    const heading = document.createElement("h3");
    heading.className = "settings-koch-detail__heading";
    heading.textContent = "Exercises";
    wrap.appendChild(heading);

    const exercises = Array.isArray(record.exercises) ? record.exercises : [];
    const legacyAnswers = Array.isArray(record.answers) ? record.answers : [];

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
    const normalised = exercises.map((rawExercise, idx) =>
        normalizeExerciseEntry(rawExercise, legacyAnswers[idx], idx),
    );
    normalised.forEach((exercise, idx) => {
        const analysis = exercise.analysis || {};
        const tr = document.createElement("tr");

        const idxCell = document.createElement("td");
        idxCell.textContent = String(exercise.index || idx + 1);
        tr.appendChild(idxCell);

        const playedCell = document.createElement("td");
        playedCell.textContent = exercise.played || "—";
        tr.appendChild(playedCell);

        const answerCell = document.createElement("td");
        if (typeof exercise.answer !== "string" || exercise.answer.length === 0) {
            answerCell.textContent = "—";
            answerCell.classList.add("settings-koch-detail__missing");
        } else {
            answerCell.textContent = exercise.answer;
        }
        tr.appendChild(answerCell);

        appendCell(tr, exercise.burden_band ?? "—");
        appendCell(tr, exercise.burden_score ?? "—");
        appendCell(
            tr,
            unitPair(analysis.symbol_correct_units, analysis.symbol_available_units),
        );
        appendCell(
            tr,
            unitPair(analysis.spacing_correct_units, analysis.spacing_available_units),
        );
        appendCell(tr, numericOrDash(analysis.repeat_weight));
        appendCell(tr, numericOrDash(analysis.evidence));
        appendCell(tr, analysis.band_state || "—");
        appendCell(tr, exercise.gear ?? analysis.gear ?? "—");

        body.appendChild(tr);
    });
    table.appendChild(body);

    const summary = buildSummaryRow(normalised);
    if (summary) {
        const tfoot = document.createElement("tfoot");
        tfoot.appendChild(summary);
        table.appendChild(tfoot);
    }
    wrap.appendChild(table);

    if (!hasSavedAnswerData(record)) {
        const note = document.createElement("p");
        note.className = "settings-koch-detail__note";
        note.textContent = "No answers saved for this session.";
        wrap.appendChild(note);
    }
    return wrap;
}

function buildSummaryRow(exercises) {
    const saved = exercises.filter((exercise) => {
        const analysis = exercise && typeof exercise === "object" ? exercise.analysis : null;
        return analysis && analysis.saved === true;
    });
    if (saved.length === 0) return null;

    let burdenTotal = 0;
    let burdenWeightedFraction = 0;
    let symbolCorrect = 0;
    let symbolAvailable = 0;
    let spacingCorrect = 0;
    let spacingAvailable = 0;
    let strongBands = 0;

    saved.forEach((exercise) => {
        const analysis = exercise.analysis || {};
        const burden = Number.isFinite(exercise.burden_score) ? exercise.burden_score : 0;
        const fraction = Number.isFinite(analysis.combined_fraction) ? analysis.combined_fraction : 0;
        burdenTotal += burden;
        burdenWeightedFraction += fraction * burden;
        if (Number.isFinite(analysis.symbol_correct_units)) {
            symbolCorrect += analysis.symbol_correct_units;
        }
        if (Number.isFinite(analysis.symbol_available_units)) {
            symbolAvailable += analysis.symbol_available_units;
        }
        if (Number.isFinite(analysis.spacing_correct_units)) {
            spacingCorrect += analysis.spacing_correct_units;
        }
        if (Number.isFinite(analysis.spacing_available_units)) {
            spacingAvailable += analysis.spacing_available_units;
        }
        // "Strong" = combined_fraction ≥ 0.95 — the same threshold the
        // gear-up rule consumes. Surfacing the count next to the
        // weighted mean makes the link to that rule explicit.
        if (fraction >= 0.95) strongBands += 1;
    });

    const weightedMean = burdenTotal > 0 ? burdenWeightedFraction / burdenTotal : 0;

    const tr = document.createElement("tr");
    tr.className = "settings-koch-detail__exercises-summary";
    appendCell(tr, "Σ");
    appendCell(tr, "");
    appendCell(tr, "");
    appendCell(tr, "");
    appendCell(tr, burdenTotal);
    appendCell(tr, unitPair(symbolCorrect, symbolAvailable));
    appendCell(tr, unitPair(spacingCorrect, spacingAvailable));
    appendCell(tr, "");
    appendCell(tr, Number(weightedMean.toFixed(3)));
    appendCell(tr, `${strongBands}/${saved.length} strong`);
    appendCell(tr, "");
    return tr;
}

function normalizeExerciseEntry(raw, legacyAnswer, idx) {
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
        return raw;
    }
    return {
        index: idx + 1,
        played: typeof raw === "string" ? raw : "",
        answer: typeof legacyAnswer === "string" ? legacyAnswer : "",
        analysis: {},
    };
}

function appendCell(row, value) {
    const cell = document.createElement("td");
    cell.textContent = String(value);
    row.appendChild(cell);
}

function unitPair(correct, available) {
    if (!Number.isFinite(correct) || !Number.isFinite(available)) return "—";
    return `${correct}/${available}`;
}

function numericOrDash(value) {
    if (!Number.isFinite(value)) return "—";
    return String(value);
}

function hasSavedAnswerData(record) {
    const exercises = Array.isArray(record.exercises) ? record.exercises : [];
    return exercises.some((exercise) => {
        const analysis = exercise && typeof exercise === "object" ? exercise.analysis : null;
        return analysis && analysis.saved === true;
    }) || (Array.isArray(record.answers) && record.answers.length > 0);
}

function renderDetailContent(container, record) {
    container.replaceChildren();
    container.appendChild(buildMetaGrid(record));
    container.appendChild(buildExercisesList(record));
}

async function loadRecord(filename) {
    if (detailCache.has(filename)) return detailCache.get(filename);
    const res = await fetch(
        `/api/koch-exercise?file=${encodeURIComponent(filename)}`,
        { cache: "no-store" },
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    detailCache.set(filename, data);
    return data;
}

async function deleteRecord(filename) {
    const res = await fetch(
        `/api/delete-koch-exercise?file=${encodeURIComponent(filename)}`,
        { method: "POST", cache: "no-store" },
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    detailCache.delete(filename);
    if (openFilename === filename) {
        detailDialog.close();
    }
    await loadKochSessions();
    window.dispatchEvent(new CustomEvent("copy-settings-records-changed", {
        detail: { kind: "koch" },
    }));
}

function clearOpenDetail() {
    if (!openFilename) return;
    const prevRow = tbody.querySelector(`tr[data-filename="${cssEscape(openFilename)}"]`);
    if (prevRow) {
        prevRow.dataset.expanded = "false";
        prevRow.setAttribute("aria-expanded", "false");
    }
    openFilename = null;
}

function rowForFilename(filename) {
    return tbody.querySelector(`tr[data-filename="${cssEscape(filename)}"]`);
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

function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(value);
    }
    // Filenames are restricted to [A-Za-z0-9.-] by the server validator,
    // so a minimal escape is enough here.
    return value.replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

async function openDetail(filename, summaryRow) {
    clearOpenDetail();
    openFilename = filename;
    summaryRow.dataset.expanded = "true";
    summaryRow.setAttribute("aria-expanded", "true");
    detailDialogTitle.textContent = "Session";
    detailDialogBody.className = "settings-koch-dialog__body";
    detailDialogBody.textContent = "Loading session…";
    updateNavButtons();
    if (!detailDialog.open) {
        detailDialog.showModal();
    }

    try {
        const record = await loadRecord(filename);
        if (openFilename !== filename) return; // user closed/switched while fetching
        detailDialogTitle.textContent = formatStartedAt(record.started_at);
        renderDetailContent(detailDialogBody, record);
        updateNavButtons();
    } catch (err) {
        detailDialogBody.textContent = `Could not load session: ${err.message}`;
        updateNavButtons();
    }
}

function attachRowHandler(tr, filename) {
    tr.classList.add("settings-koch-row");
    tr.dataset.filename = filename;
    tr.dataset.expanded = "false";
    tr.setAttribute("role", "button");
    tr.setAttribute("tabindex", "0");
    tr.setAttribute("aria-expanded", "false");
    const toggle = () => {
        if (openFilename === filename) {
            detailDialog.close();
        } else {
            openDetail(filename, tr);
        }
    };
    tr.addEventListener("click", toggle);
    tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
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
    button.setAttribute("aria-label", "Delete Koch session record");
    button.addEventListener("click", async (event) => {
        event.stopPropagation();
        const ok = window.confirm("Delete this Koch session record?");
        if (!ok) return;
        try {
            button.disabled = true;
            await deleteRecord(filename);
        } catch (err) {
            button.disabled = false;
            window.alert(`Could not delete Koch session: ${err.message}`);
        }
    });
    button.addEventListener("keydown", (event) => {
        event.stopPropagation();
    });
    cell.appendChild(button);
    row.appendChild(cell);
}

detailDialog.addEventListener("close", () => {
    detailDialogTitle.textContent = "Session";
    detailDialogBody.replaceChildren();
    clearOpenDetail();
    updateNavButtons();
});

detailDialog.addEventListener("click", (event) => {
    if (event.target === detailDialog) {
        detailDialog.close();
    }
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

function renderRows(records) {
    tbody.replaceChildren();
    openFilename = null;
    currentRecords = records;
    updateNavButtons();
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

        appendDeleteCell(tr, rec.filename);
        attachRowHandler(tr, rec.filename);
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
            currentRecords = [];
            openFilename = null;
            updateNavButtons();
            tbody.replaceChildren();
            return;
        }
        metaEl.textContent = `${records.length} saved session${records.length === 1 ? "" : "s"} in ${data.save_directory}`;
        renderRows(records);
    } catch (err) {
        metaEl.textContent = `Could not load saved sessions: ${err.message}`;
        currentRecords = [];
        openFilename = null;
        updateNavButtons();
        tbody.replaceChildren();
    }
}

loadKochSessions();
