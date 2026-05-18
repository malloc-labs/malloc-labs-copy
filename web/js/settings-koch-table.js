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

let openFilename = null;
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
    const thead = document.createElement("thead");
    thead.innerHTML =
        "<tr><th scope=\"col\">#</th>" +
        "<th scope=\"col\">Played</th>" +
        "<th scope=\"col\">You typed</th>" +
        "<th scope=\"col\">Band</th>" +
        "<th scope=\"col\">Burden</th>" +
        "<th scope=\"col\">Symbols</th>" +
        "<th scope=\"col\">Spacing</th>" +
        "<th scope=\"col\">Repeat</th>" +
        "<th scope=\"col\">Evidence</th>" +
        "<th scope=\"col\">State</th>" +
        "<th scope=\"col\">Gear</th></tr>";
    table.appendChild(thead);

    const body = document.createElement("tbody");
    exercises.forEach((rawExercise, idx) => {
        const exercise = normalizeExerciseEntry(rawExercise, legacyAnswers[idx], idx);
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
    wrap.appendChild(table);

    if (!hasSavedAnswerData(record)) {
        const note = document.createElement("p");
        note.className = "settings-koch-detail__note";
        note.textContent = "No answers saved for this session.";
        wrap.appendChild(note);
    }
    return wrap;
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

function clearOpenDetail() {
    if (!openFilename) return;
    const prevRow = tbody.querySelector(`tr[data-filename="${cssEscape(openFilename)}"]`);
    if (prevRow) {
        prevRow.dataset.expanded = "false";
        prevRow.setAttribute("aria-expanded", "false");
    }
    openFilename = null;
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
    if (!detailDialog.open) {
        detailDialog.showModal();
    }

    try {
        const record = await loadRecord(filename);
        if (openFilename !== filename) return; // user closed/switched while fetching
        detailDialogTitle.textContent = formatStartedAt(record.started_at);
        renderDetailContent(detailDialogBody, record);
    } catch (err) {
        detailDialogBody.textContent = `Could not load session: ${err.message}`;
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

detailDialog.addEventListener("close", () => {
    detailDialogTitle.textContent = "Session";
    detailDialogBody.replaceChildren();
    clearOpenDetail();
});

detailDialog.addEventListener("click", (event) => {
    if (event.target === detailDialog) {
        detailDialog.close();
    }
});

function renderRows(records) {
    tbody.replaceChildren();
    openFilename = null;
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
