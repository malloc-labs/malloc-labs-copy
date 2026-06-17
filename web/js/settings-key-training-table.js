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

function numberValue(value) {
    return Number.isFinite(value) ? value : 0;
}

function countFaults(record) {
    return numberValue(record.fault_count)
        || numberValue(record.timing_fault_count) + numberValue(record.wrong_symbol_count);
}

function hardestSymbolLabel(record) {
    const symbol = record.hardest_symbol;
    const count = numberValue(record.hardest_symbol_faults);
    return symbol ? `${symbol} (${count})` : "—";
}

function buildModeSummary(records) {
    const byMode = {};
    for (const rec of records) {
        const m = rec.training_mode || "unknown";
        if (!byMode[m]) {
            byMode[m] = {
                sessions: 0,
                completed: 0,
                exercises: 0,
                clean: 0,
                repeats: 0,
                faults: 0,
            };
        }
        byMode[m].sessions += 1;
        if (rec.session_status === "completed") byMode[m].completed += 1;
        byMode[m].exercises += numberValue(rec.exercise_count);
        byMode[m].clean += numberValue(rec.clean_exercise_count);
        byMode[m].repeats += numberValue(rec.restart_count);
        byMode[m].faults += countFaults(rec);
    }

    summaryModesEl.replaceChildren();
    const modes = MODE_ORDER.filter((m) => byMode[m]);
    if (modes.length === 0) return;

    for (const mode of modes) {
        const stats = byMode[mode];
        const cleanRate = stats.exercises > 0
            ? `${Math.round((stats.clean / stats.exercises) * 100)}%`
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
            ["Completed", stats.completed],
            ["Exercises", stats.exercises],
            ["Clean", stats.clean],
            ["Clean rate", cleanRate],
            ["Repeats", stats.repeats],
            ["Faults", stats.faults],
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
    const summary = summariseRecord(record);
    [
        ["Started", formatStartedAt(record.started_at)],
        ["Ended", formatStartedAt(record.ended_at)],
        ["Duration", formatDuration(record.started_at, record.ended_at)],
        ["Mode", MODE_LABELS[record.training_mode] || record.training_mode || "—"],
        ["Status", record.session_status || "—"],
        ["Character speed", Number.isFinite(audio.character_speed_wpm) ? `${audio.character_speed_wpm} WPM` : "—"],
        ["Claimed set", claimed],
        ["Exercises", summary.exerciseCount],
        ["Clean exercises", summary.cleanExerciseCount],
        ["Repeated exercises", summary.repeatedExerciseCount],
        ["Line repeats", summary.restartCount],
        ["Faults", summary.faultCount],
        ["Hardest target", summary.hardestSymbol ? `${summary.hardestSymbol} (${summary.hardestSymbolFaults})` : "—"],
        ["Set ID", gen.set_id || "—"],
    ].forEach(([label, value]) => {
        const dt = document.createElement("dt");
        dt.textContent = label;
        const dd = document.createElement("dd");
        dd.textContent = value;
        grid.append(dt, dd);
    });
    return grid;
}

function summariseRecord(record) {
    const attempts = Array.isArray(record.attempts) ? record.attempts : [];
    const exercises = Array.isArray(record.exercises) ? record.exercises : [];
    const byExercise = buildExerciseSummaries(attempts);
    const faultCounts = {};
    let timingFaultCount = 0;
    let wrongSymbolCount = 0;
    let restartCount = 0;

    for (const a of attempts) {
        const result = a.result;
        if (result === "timing-fail") timingFaultCount += 1;
        if (result === "wrong-symbol") wrongSymbolCount += 1;
        if (a.action === "restart-line") restartCount += 1;
        if (result === "timing-fail" || result === "wrong-symbol") {
            const symbol = a.target_symbol;
            if (symbol) faultCounts[symbol] = (faultCounts[symbol] || 0) + 1;
        }
    }

    const hardest = Object.entries(faultCounts).sort((a, b) => b[1] - a[1])[0] || ["", 0];
    const exerciseRows = [...byExercise.values()];
    return {
        exerciseCount: exercises.length,
        cleanExerciseCount: exerciseRows.filter((ex) => ex.status === "clean").length,
        repeatedExerciseCount: exerciseRows.filter((ex) => ex.restarts > 0).length,
        restartCount,
        timingFaultCount,
        wrongSymbolCount,
        faultCount: timingFaultCount + wrongSymbolCount,
        hardestSymbol: hardest[0],
        hardestSymbolFaults: hardest[1],
    };
}

function buildExerciseSummaries(attempts) {
    const byExercise = new Map();
    for (const a of attempts) {
        const idx = a.exercise_index ?? 0;
        if (!byExercise.has(idx)) {
            byExercise.set(idx, {
                index: idx,
                target: a.target || "—",
                accepted: 0,
                timingFails: 0,
                wrongSymbols: 0,
                restarts: 0,
                completed: false,
                scoredEvents: 0,
            });
        }
        const ex = byExercise.get(idx);
        ex.scoredEvents += 1;
        if (a.result === "accepted") ex.accepted += 1;
        if (a.result === "timing-fail") ex.timingFails += 1;
        if (a.result === "wrong-symbol") ex.wrongSymbols += 1;
        if (a.action === "restart-line") ex.restarts += 1;
        if (a.action === "complete-exercise" || a.action === "complete-session") ex.completed = true;
    }

    for (const ex of byExercise.values()) {
        const faults = ex.timingFails + ex.wrongSymbols;
        if (ex.completed && faults === 0 && ex.restarts === 0) {
            ex.status = "clean";
        } else if (ex.completed && ex.restarts > 0) {
            ex.status = "repeated";
        } else if (ex.completed) {
            ex.status = "completed";
        } else if (ex.restarts > 0 || faults > 0) {
            ex.status = "needs repeat";
        } else {
            ex.status = "incomplete";
        }
        ex.faults = faults;
        ex.exerciseAttempts = 1 + ex.restarts;
    }
    return byExercise;
}

function buildAttemptSummaryTable(record) {
    const attempts = Array.isArray(record.attempts) ? record.attempts : [];
    if (attempts.length === 0) return null;

    const byExercise = buildExerciseSummaries(attempts);

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
        { label: "Status" },
        { label: "Exercise attempts", tooltip: "One plus the number of line repeats" },
        { label: "Faults", tooltip: "Timing faults plus wrong-symbol faults" },
        { label: "Timing", tooltip: "Symbols where the spacing failed" },
        { label: "Wrong", tooltip: "Symbols where the decoded symbol differed from the target" },
        { label: "Repeats", tooltip: "Times the line was repeated after a fault" },
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
        row.dataset.status = ex.status;
        appendCell(row, idx);
        appendCell(row, ex.target);
        appendCell(row, ex.status);
        appendCell(row, ex.exerciseAttempts);
        appendCell(row, ex.faults);
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
        appendCell(row, rec.exercise_count ?? "—");
        appendCell(row, rec.clean_exercise_count ?? "—");
        appendCell(row, rec.restart_count ?? "—");
        appendCell(row, countFaults(rec));
        appendCell(row, hardestSymbolLabel(rec));
        appendCell(row, formatDuration(rec.started_at, rec.ended_at));
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
