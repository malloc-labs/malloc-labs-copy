// Settings page — saved Copy > Key sessions table.

import { buildExerciseBlock } from "./rhythm-review.js";
import { appendCell, formatDuration, formatStartedAt, fraction } from "./settings-formatters.js";
import { createRecordTableController } from "./settings-record-table.js";

const tbody = document.getElementById("settings-copy-key-tbody");
const metaEl = document.getElementById("settings-copy-key-meta");
const detailDialog = document.getElementById("settings-copy-key-dialog");
const detailDialogTitle = document.getElementById("settings-copy-key-dialog-title");
const detailDialogBody = document.getElementById("settings-copy-key-dialog-body");
const prevButton = document.getElementById("settings-copy-key-dialog-prev");
const nextButton = document.getElementById("settings-copy-key-dialog-next");
const countEl = document.getElementById("settings-copy-key-dialog-count");

function formatSentWithGaps(bucket) {
    let out = "";
    for (const event of bucket) {
        if (out && event.leading_gap === "word") out += " ";
        out += event.symbol || "?";
    }
    return out;
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

const EXERCISES_COLUMNS = [
    { label: "#" },
    { label: "Target" },
    { label: "Sent" },
    {
        label: "Attempts",
        tooltip:
            "How many keying attempts you made on this target. The scored row picks your best " +
            "attempt; the others are kept on the record but not double-counted.",
    },
    {
        label: "Spacing",
        tooltip:
            "Spacing accuracy — word boundaries placed correctly between decoded symbols. " +
            "Contributes 10% of the combined fraction.",
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
            "in the readable range. Contributes 10% of the combined fraction.",
    },
    {
        label: "Combined",
        tooltip:
            "Combined fraction — weighted total: 0.55 Symbols + 0.10 Spacing + 0.20 Formation + " +
            "0.10 Gap + 0.05 Decode.",
    },
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
            "exercise to head-copy and key back.",
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
            if (idx >= EXERCISES_COLUMNS.length - 2) {
                th.dataset.tooltipAlign = "right";
            }
        }
        tr.appendChild(th);
    });
    thead.appendChild(tr);
    return thead;
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

    table.appendChild(buildExercisesHead());


    const body = document.createElement("tbody");
    exercises.forEach((exercise, idx) => {
        const bucket = sentBuckets[idx] || [];
        const correct = isSentCorrect(exercise.target, bucket);
        const analysis = exercise.analysis || {};
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
        } else if (bucket.length > 0) {
            sentCell.textContent = formatSentWithGaps(bucket);
        }
        row.appendChild(sentCell);

        appendCell(row, analysis.attempt_count ?? "-");
        appendCell(row, fraction(analysis.spacing_fraction));
        appendCell(row, fraction(analysis.formation_fraction));
        appendCell(row, fraction(analysis.gap_timing_fraction));
        appendCell(row, fraction(analysis.combined_fraction));
        appendCell(row, exercise.burden_band ?? "-");
        appendCell(row, exercise.burden_score ?? "-");
        appendCell(row, analysis.band_state || "-");
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

createRecordTableController({
    tbody,
    metaEl,
    detailDialog,
    detailDialogTitle,
    detailDialogBody,
    prevButton,
    nextButton,
    countEl,
    listEndpoint: "/api/copy-key-sessions",
    recordEndpoint: "/api/copy-key-session",
    deleteEndpoint: "/api/delete-copy-key-session",
    changedKind: "copy-key",
    dialogTitle: "Copy > Key session",
    loadingText: "Loading session...",
    emptyText: (data) =>
        `No saved copy > key sessions in ${data.save_directory || "save directory"}.`,
    countText: (records, data) =>
        `${records.length} saved session${records.length === 1 ? "" : "s"} in ${data.save_directory}`,
    listErrorText: (err) => `Could not load saved sessions: ${err.message}`,
    loadErrorText: (err) => `Could not load session: ${err.message}`,
    deleteConfirmText: "Delete this Copy > Key session record?",
    deleteAriaLabel: "Delete Copy > Key session record",
    deleteErrorText: (err) => `Could not delete Copy > Key session: ${err.message}`,
    detailTitle: (record) => formatStartedAt(record.started_at),
    renderDetail,
    renderRowCells: (row, rec, idx) => {
        appendCell(row, idx + 1);
        appendCell(row, formatStartedAt(rec.started_at));
        appendCell(row, Array.isArray(rec.claimed_set) ? rec.claimed_set.join(" ") : "-");
        appendCell(row, rec.exercise_count ?? "-");
    },
});
