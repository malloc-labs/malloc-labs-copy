// Settings page — saved Send Cadence sessions table.

import { appendCell, formatDuration, formatStartedAt, fraction } from "./settings-formatters.js";
import { createRecordTableController } from "./settings-record-table.js";

const tbody = document.getElementById("settings-key-tbody");
const metaEl = document.getElementById("settings-key-meta");
const detailDialog = document.getElementById("settings-key-dialog");
const detailDialogTitle = document.getElementById("settings-key-dialog-title");
const detailDialogBody = document.getElementById("settings-key-dialog-body");
const prevButton = document.getElementById("settings-key-dialog-prev");
const nextButton = document.getElementById("settings-key-dialog-next");
const countEl = document.getElementById("settings-key-dialog-count");

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

createRecordTableController({
    tbody,
    metaEl,
    detailDialog,
    detailDialogTitle,
    detailDialogBody,
    prevButton,
    nextButton,
    countEl,
    listEndpoint: "/api/cadence-sends",
    recordEndpoint: "/api/cadence-send",
    deleteEndpoint: "/api/delete-cadence-send",
    changedKind: "key",
    dialogTitle: "Send session",
    loadingText: "Loading send session...",
    emptyText: (data) =>
        `No saved send sessions in ${data.save_directory || "save directory"}.`,
    countText: (records, data) =>
        `${records.length} saved send session${records.length === 1 ? "" : "s"} in ${data.save_directory}`,
    listErrorText: (err) => `Could not load saved send sessions: ${err.message}`,
    loadErrorText: (err) => `Could not load send session: ${err.message}`,
    deleteConfirmText: "Delete this Key send session record?",
    deleteAriaLabel: "Delete Key send session record",
    deleteErrorText: (err) => `Could not delete Key send session: ${err.message}`,
    detailTitle: (record) => formatStartedAt(record.started_at),
    renderDetail,
    renderRowCells: (row, rec, idx) => {
        appendCell(row, idx + 1);
        appendCell(row, formatStartedAt(rec.started_at));
        appendCell(row, Array.isArray(rec.claimed_set) ? rec.claimed_set.join(" ") : "-");
        appendCell(row, rec.exercise_count ?? "-");
    },
});
