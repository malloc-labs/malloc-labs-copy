// Settings page — Key Training sessions table, mode summary, and symbol fault heatmap.

import { appendCell, formatDuration, formatStartedAt } from "./settings-formatters.js";
import { createRecordTableController } from "./settings-record-table.js";

// ─── DOM refs ────────────────────────────────────────────────────────────────

const tbody = document.getElementById("settings-kt-tbody");
const metaEl = document.getElementById("settings-kt-meta");
const detailDialog = document.getElementById("settings-kt-dialog");
const detailDialogTitle = document.getElementById("settings-kt-dialog-title");
const detailDialogBody = document.getElementById("settings-kt-dialog-body");
const prevButton = document.getElementById("settings-kt-dialog-prev");
const nextButton = document.getElementById("settings-kt-dialog-next");
const countEl = document.getElementById("settings-kt-dialog-count");
const summarySection = document.getElementById("settings-kt-summary");
const summaryModesEl = document.getElementById("settings-kt-summary-modes");
const heatmapSection = document.getElementById("settings-kt-heatmap");
const heatmapGridEl = document.getElementById("settings-kt-heatmap-grid");

// ─── Mode summary panel ───────────────────────────────────────────────────────

const MODE_LABELS = { scales: "Scales", intervals: "Intervals", etudes: "Etudes" };
const MODE_ORDER = ["scales", "intervals", "etudes"];

function buildModeSummary(records) {
    const byMode = {};
    for (const rec of records) {
        const m = rec.training_mode || "unknown";
        if (!byMode[m]) {
            byMode[m] = { sessions: 0, exercises: 0, attempts: 0 };
        }
        byMode[m].sessions += 1;
        byMode[m].exercises += rec.exercise_count || 0;
        byMode[m].attempts += rec.attempt_count || 0;
    }

    summaryModesEl.replaceChildren();
    const modes = MODE_ORDER.filter((m) => byMode[m]);
    if (modes.length === 0) return;

    for (const mode of modes) {
        const stats = byMode[mode];
        const avgAttempts =
            stats.exercises > 0
                ? (stats.attempts / stats.exercises).toFixed(1)
                : "—";

        const card = document.createElement("div");
        card.className = "settings-kt-mode-card";

        const title = document.createElement("h4");
        title.className = "settings-kt-mode-card__title";
        title.textContent = MODE_LABELS[mode] || mode;
        card.appendChild(title);

        const dl = document.createElement("dl");
        dl.className = "settings-kt-mode-card__stats";
        [
            ["Sessions", stats.sessions],
            ["Exercises", stats.exercises],
            ["Avg attempts / exercise", avgAttempts],
        ].forEach(([label, value]) => {
            const dt = document.createElement("dt");
            dt.textContent = label;
            const dd = document.createElement("dd");
            dd.textContent = value;
            dl.append(dt, dd);
        });
        card.appendChild(dl);
        summaryModesEl.appendChild(card);
    }

    summarySection.hidden = false;
}

// ─── Symbol fault heatmap ─────────────────────────────────────────────────────

function buildFaultHeatmap(records) {
    // Aggregate fault_counts across all records
    const totals = {};
    for (const rec of records) {
        const fc = rec.fault_counts || {};
        for (const [sym, count] of Object.entries(fc)) {
            totals[sym] = (totals[sym] || 0) + count;
        }
    }

    const entries = Object.entries(totals).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) return;

    const maxCount = entries[0][1];
    heatmapGridEl.replaceChildren();

    for (const [sym, count] of entries) {
        const intensity = maxCount > 0 ? count / maxCount : 0;
        const cell = document.createElement("div");
        cell.className = "settings-kt-heatmap__cell";
        cell.style.setProperty("--kt-heat", intensity.toFixed(3));
        cell.title = `${sym}: ${count} fault${count === 1 ? "" : "s"}`;

        const symEl = document.createElement("span");
        symEl.className = "settings-kt-heatmap__sym";
        symEl.textContent = sym;

        const countEl = document.createElement("span");
        countEl.className = "settings-kt-heatmap__count";
        countEl.textContent = count;

        cell.append(symEl, countEl);
        heatmapGridEl.appendChild(cell);
    }

    heatmapSection.hidden = false;
}

// ─── Session detail dialog ────────────────────────────────────────────────────

function buildMetaGrid(record) {
    const grid = document.createElement("dl");
    grid.className = "settings-koch-detail__meta";
    const claimed = Array.isArray(record.claimed_set) ? record.claimed_set.join(" ") : "—";
    const audio = record.audio || {};
    const gen = record.generation || {};
    [
        ["Started", formatStartedAt(record.started_at)],
        ["Ended", formatStartedAt(record.ended_at)],
        ["Duration", formatDuration(record.started_at, record.ended_at)],
        ["Mode", MODE_LABELS[record.training_mode] || record.training_mode || "—"],
        ["Status", record.session_status || "—"],
        ["Character speed", Number.isFinite(audio.character_speed_wpm) ? `${audio.character_speed_wpm} WPM` : "—"],
        ["Claimed set", claimed],
        ["Set ID", gen.set_id || "—"],
        ["Session in set", gen.set_session ?? "—"],
        ["Engine", record.engine_version ? `v${record.engine_version}` : "—"],
    ].forEach(([label, value]) => {
        const dt = document.createElement("dt");
        dt.textContent = label;
        const dd = document.createElement("dd");
        dd.textContent = value;
        grid.append(dt, dd);
    });
    return grid;
}

function buildAttemptSummaryTable(record) {
    const attempts = Array.isArray(record.attempts) ? record.attempts : [];
    if (attempts.length === 0) return null;

    // Group attempts by exercise_index
    const byExercise = new Map();
    for (const a of attempts) {
        const idx = a.exercise_index ?? 0;
        if (!byExercise.has(idx)) {
            byExercise.set(idx, {
                target: a.target || "—",
                accepted: 0,
                timingFails: 0,
                wrongSymbols: 0,
                restarts: 0,
                taints: 0,
            });
        }
        const ex = byExercise.get(idx);
        if (a.result === "accepted") ex.accepted += 1;
        if (a.result === "timing-fail") ex.timingFails += 1;
        if (a.result === "wrong-symbol") ex.wrongSymbols += 1;
        if (a.action === "restart-line") ex.restarts += 1;
        if (a.action === "taint-line") ex.taints += 1;
    }

    const wrap = document.createElement("div");
    wrap.className = "settings-koch-detail__exercises";

    const heading = document.createElement("h3");
    heading.className = "settings-koch-detail__heading";
    heading.textContent = "Exercise breakdown";
    wrap.appendChild(heading);

    const table = document.createElement("table");
    table.className = "settings-koch-detail__exercises-table";

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    [
        { label: "#" },
        { label: "Target" },
        { label: "Accepted", tooltip: "Symbols accepted on first or subsequent attempt" },
        { label: "Timing faults", tooltip: "Symbols where the gap was too wide (timing-fail)" },
        { label: "Wrong symbols", tooltip: "Symbols where the wrong character was sent" },
        { label: "Restarts", tooltip: "Times the line was restarted after a fault" },
    ].forEach(({ label, tooltip }) => {
        const th = document.createElement("th");
        th.scope = "col";
        th.textContent = label;
        if (tooltip) th.dataset.tooltip = tooltip;
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const body = document.createElement("tbody");
    for (const [idx, ex] of [...byExercise.entries()].sort((a, b) => a[0] - b[0])) {
        const row = document.createElement("tr");
        appendCell(row, idx);
        appendCell(row, ex.target);
        appendCell(row, ex.accepted);
        appendCell(row, ex.timingFails);
        appendCell(row, ex.wrongSymbols);
        appendCell(row, ex.restarts);
        body.appendChild(row);
    }
    table.appendChild(body);
    wrap.appendChild(table);
    return wrap;
}

function renderDetail(record) {
    detailDialogBody.replaceChildren();
    detailDialogBody.appendChild(buildMetaGrid(record));
    const exerciseTable = buildAttemptSummaryTable(record);
    if (exerciseTable) detailDialogBody.appendChild(exerciseTable);
}

// ─── Table controller ─────────────────────────────────────────────────────────

const { loadSessions } = createRecordTableController({
    tbody,
    metaEl,
    detailDialog,
    detailDialogTitle,
    detailDialogBody,
    prevButton,
    nextButton,
    countEl,
    listEndpoint: "/api/key-training-sessions",
    recordEndpoint: "/api/key-training-session",
    deleteEndpoint: "/api/delete-key-training-session",
    changedKind: "key-training",
    dialogTitle: "Key training session",
    loadingText: "Loading key training session…",
    emptyText: (data) =>
        `No saved key training sessions in ${data.save_directory || "save directory"}.`,
    countText: (records, data) =>
        `${records.length} saved key training session${records.length === 1 ? "" : "s"} in ${data.save_directory}`,
    listErrorText: (err) => `Could not load key training sessions: ${err.message}`,
    loadErrorText: (err) => `Could not load key training session: ${err.message}`,
    deleteConfirmText: "Delete this key training session record?",
    deleteAriaLabel: "Delete key training session record",
    deleteErrorText: (err) => `Could not delete key training session: ${err.message}`,
    detailTitle: (record) =>
        `${MODE_LABELS[record.training_mode] || record.training_mode || "Key training"} — ${formatStartedAt(record.started_at)}`,
    renderDetail,
    renderRowCells: (row, rec, idx) => {
        appendCell(row, idx + 1);
        appendCell(row, formatStartedAt(rec.started_at));
        appendCell(row, MODE_LABELS[rec.training_mode] || rec.training_mode || "—");
        appendCell(row, rec.session_status || "—");
        appendCell(row, Array.isArray(rec.claimed_set) ? rec.claimed_set.join(" ") : "—");
        appendCell(row, rec.exercise_count ?? "—");
        appendCell(row, rec.attempt_count ?? "—");
    },
});

// ─── Wire up summary + heatmap after list loads ───────────────────────────────

// Intercept the list response to build the summary panels.
// We fetch the list ourselves once the controller has loaded it by listening
// for the first render cycle.
(async () => {
    try {
        const res = await fetch("/api/key-training-sessions", { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        const records = Array.isArray(data.records) ? data.records : [];
        if (records.length > 0) {
            buildModeSummary(records);
            buildFaultHeatmap(records);
        }
    } catch {
        // silently ignore — summary panels are optional enhancements
    }
})();
