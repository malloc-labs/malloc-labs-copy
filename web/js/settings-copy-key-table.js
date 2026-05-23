// Settings page — saved Copy > Key sessions table.

import { buildExerciseBlock } from "./rhythm-review.js";

const tbody = document.getElementById("settings-copy-key-tbody");
const metaEl = document.getElementById("settings-copy-key-meta");
const detailDialog = document.getElementById("settings-copy-key-dialog");
const detailDialogTitle = document.getElementById("settings-copy-key-dialog-title");
const detailDialogBody = document.getElementById("settings-copy-key-dialog-body");
const prevButton = document.getElementById("settings-copy-key-dialog-prev");
const nextButton = document.getElementById("settings-copy-key-dialog-next");
const countEl = document.getElementById("settings-copy-key-dialog-count");

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

// Split the flat sent array into per-exercise buckets by detecting BK
// (B immediately followed by K) boundaries. BK pairs are stripped.
function splitSentByExercise(sent) {
    const buckets = [[]];
    for (let i = 0; i < sent.length; i++) {
        const event = sent[i];
        if (event.symbol === "K" && i > 0 && sent[i - 1].symbol === "B") {
            const bucket = buckets[buckets.length - 1];
            if (bucket.length > 0 && bucket[bucket.length - 1].symbol === "B") {
                bucket.pop();
            }
            buckets.push([]);
            continue;
        }
        buckets[buckets.length - 1].push(event);
    }
    return buckets;
}

// Convert raw sent events into the shape buildExerciseBlock expects.
function toReviewEvents(rawEvents) {
    const events = [];
    let prevEndedAt = null;
    rawEvents.forEach((raw, idx) => {
        const startedAt = Number(raw.started_at);
        const endedAt = Number(raw.ended_at);
        let leadingGapMs = null;
        if (Number.isFinite(startedAt) && Number.isFinite(prevEndedAt)) {
            leadingGapMs = Math.max(0, (startedAt - prevEndedAt) * 1000);
        }
        events.push({
            symbol: raw.symbol,
            leadingGap: raw.leading_gap || "none",
            leadingGapMs,
            isAttemptStart: idx === 0,
        });
        if (Number.isFinite(endedAt)) prevEndedAt = endedAt;
    });
    return events;
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

function isSentCorrect(target, bucket) {
    if (!target || bucket.length === 0) return false;
    const targetFlat = target.replace(/ /g, "");
    const sentFlat = bucket.map((s) => s.symbol).join("");
    return sentFlat === targetFlat;
}

function buildExercisesTable(record, sentBuckets) {
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

    const audio = record.audio || {};
    const charWpm = Number(audio.character_speed_wpm) || 20;
    const ditMs = 1200 / charWpm;

    const table = document.createElement("table");
    table.className = "settings-koch-detail__exercises-table";

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    ["#", "Target", "Sent", "Band", "Burden", "Gear"].forEach((label) => {
        const th = document.createElement("th");
        th.scope = "col";
        th.textContent = label;
        headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const body = document.createElement("tbody");
    exercises.forEach((exercise, idx) => {
        const bucket = sentBuckets[idx] || [];
        const correct = isSentCorrect(exercise.target, bucket);
        const row = document.createElement("tr");
        appendCell(row, exercise.index || idx + 1);
        appendCell(row, exercise.target || "-");

        const sentCell = document.createElement("td");
        if (correct) {
            sentCell.appendChild(
                buildExerciseBlock({
                    exercise: exercise.target,
                    events: toReviewEvents(bucket),
                    ditMs,
                }),
            );
        }
        row.appendChild(sentCell);

        appendCell(row, exercise.burden_band ?? "-");
        appendCell(row, exercise.burden_score ?? "-");
        appendCell(row, exercise.gear ?? "-");
        body.appendChild(row);
    });
    table.appendChild(body);
    wrap.appendChild(table);
    return wrap;
}

function renderDetail(record) {
    detailDialogBody.replaceChildren();
    const sent = Array.isArray(record.sent) ? record.sent : [];
    const sentBuckets = splitSentByExercise(sent);
    detailDialogBody.appendChild(buildMetaGrid(record));
    detailDialogBody.appendChild(buildExercisesTable(record, sentBuckets));
}

async function loadRecord(filename) {
    if (detailCache.has(filename)) return detailCache.get(filename);
    const res = await fetch(`/api/copy-key-session?file=${encodeURIComponent(filename)}`, {
        cache: "no-store",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    detailCache.set(filename, data);
    return data;
}

async function deleteRecord(filename) {
    const res = await fetch(
        `/api/delete-copy-key-session?file=${encodeURIComponent(filename)}`,
        { cache: "no-store" },
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    detailCache.delete(filename);
    if (openFilename === filename) {
        detailDialog.close();
    }
    await loadCopyKeySessions();
    window.dispatchEvent(new CustomEvent("copy-settings-records-changed", {
        detail: { kind: "copy-key" },
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
    detailDialogTitle.textContent = "Copy > Key session";
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
    button.setAttribute("aria-label", "Delete Copy > Key session record");
    button.addEventListener("click", async (event) => {
        event.stopPropagation();
        const ok = window.confirm("Delete this Copy > Key session record?");
        if (!ok) return;
        try {
            button.disabled = true;
            await deleteRecord(filename);
        } catch (err) {
            button.disabled = false;
            window.alert(`Could not delete Copy > Key session: ${err.message}`);
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

async function loadCopyKeySessions() {
    try {
        const res = await fetch("/api/copy-key-sessions", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const records = Array.isArray(data.records) ? data.records : [];
        if (records.length === 0) {
            metaEl.textContent = `No saved copy > key sessions in ${data.save_directory || "save directory"}.`;
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

if (tbody) loadCopyKeySessions();

detailDialog.addEventListener("close", () => {
    detailDialogTitle.textContent = "Copy > Key session";
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
