// Settings page — saved Symbol Recognition sessions table.
//
// Fetches /api/recognitions and renders saved records grouped by their
// 8-session recognition set when that metadata is available. Clicking a
// row opens a detail dialog with an exercise-level summary derived from
// the voice-honest `analysis` block (recognition_analysis): what was
// played, what Vosk heard, what the learner committed after review,
// per-exercise outcome counts, and the two confusion streams.
//
// Recognition state and gear are backend evidence, not learner-facing
// grades. A silent exercise is neutral ("nothing heard"), neither
// evidence nor error.
// The Heard column is voice-derived and may differ from the learner's
// editable Answer by design. Backend evidence, not a score (spec §9).

import { appendCell, formatDuration, formatStartedAt } from "./settings-formatters.js";
import { createRecordTableController } from "./settings-record-table.js";

const tbody = document.getElementById("settings-recognition-tbody");
const metaEl = document.getElementById("settings-recognition-records-meta");
const detailDialog = document.getElementById("settings-recognition-dialog");
const detailDialogTitle = document.getElementById("settings-recognition-dialog-title");
const detailDialogBody = document.getElementById("settings-recognition-dialog-body");
const prevButton = document.getElementById("settings-recognition-dialog-prev");
const nextButton = document.getElementById("settings-recognition-dialog-next");
const countEl = document.getElementById("settings-recognition-dialog-count");

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
            "Self-corrections or recovered substitutions seen in review evidence.",
    },
    {
        label: "Miss",
        tooltip: "Windows where no symbol was heard.",
    },
    {
        label: "Confusions",
        tooltip:
            "Committed confusions and caught false starts, kept separate. 'caught' means " +
            "the learner superseded or recovered from the false start.",
    },
    {
        label: "State",
        tooltip:
            "Recognition evidence state from committed voice windows: silent, low, " +
            "building, steady, strong, or exact.",
    },
    {
        label: "Gear",
        tooltip:
            "Hidden Recognition progression gear for this exercise slot. Strong runs nudge " +
            "it up; repeated low runs nudge it down.",
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

function symbolsForExercise(record, exercise) {
    const exerciseIndex = exercise?.index;
    const symbols = Array.isArray(record.symbols) ? record.symbols : [];
    return symbols
        .filter((entry) => entry && entry.exercise_index === exerciseIndex)
        .sort((a, b) => Number(a.t_on) - Number(b.t_on));
}

function heardEventsForExercise(exercise) {
    const capture = Array.isArray(exercise?.voice_capture) ? exercise.voice_capture : [];
    const events = [];
    capture.forEach((entry) => {
        const timed = Array.isArray(entry?.symbol_events) ? entry.symbol_events : [];
        if (timed.length) {
            timed.forEach((event) => {
                const index = Number(event.index);
                const t = Number(event.t);
                if (!Number.isInteger(index) || !Number.isFinite(t)) return;
                events[index - 1] = {
                    symbol: event.symbol || "?",
                    t,
                    source: event.source || "partial",
                };
            });
            return;
        }
        const symbols = Array.isArray(entry?.symbols) ? entry.symbols : [];
        const t = Number(entry?.first_partial_t ?? entry?.t);
        if (!Number.isFinite(t)) return;
        symbols.forEach((symbol) => {
            events.push({
                symbol,
                t,
                source: entry.first_partial_t == null ? "final" : "partial",
            });
        });
    });
    return events;
}

function recognitionLatencyBand(latencyMs) {
    if (!Number.isFinite(latencyMs)) return "missing";
    if (latencyMs <= 1500) return "fluent";
    if (latencyMs <= 3000) return "working";
    return "hesitant";
}

function buildRecognitionHeardBlock(record, exercise) {
    const played = symbolsForExercise(record, exercise);
    if (!played.length) return null;
    const heard = heardEventsForExercise(exercise);
    const responses = played.map((target, idx) => {
        const event = heard[idx];
        const tOff = Number(target.t_off);
        if (!event || !Number.isFinite(event.t) || !Number.isFinite(tOff)) return null;
        return {
            symbol: event.symbol,
            source: event.source,
            latencyMs: Math.max(0, Math.round((event.t - tOff) * 1000)),
        };
    });
    if (!responses.some(Boolean)) return null;

    const block = document.createElement("div");
    block.className = "settings-recognition-heard";
    played.forEach((target, idx) => {
        const response = responses[idx];
        const responseWrap = document.createElement("span");
        if (response) {
            const band = recognitionLatencyBand(response.latencyMs);
            responseWrap.className =
                `settings-recognition-heard__symbol ` +
                `settings-recognition-heard__symbol--${band}`;
            responseWrap.title =
                `Target ${target.symbol || "?"}; heard ${response.symbol} ${band} ` +
                `(${response.source || "heard"}): ` +
                `${(response.latencyMs / 1000).toFixed(2)}s after symbol end`;
            responseWrap.setAttribute("aria-label", responseWrap.title);
            responseWrap.textContent = response.symbol;
        } else {
            responseWrap.className =
                "settings-recognition-heard__symbol " +
                "settings-recognition-heard__symbol--missing";
            responseWrap.title = `Target ${target.symbol || "?"}; no timed voice response`;
            responseWrap.setAttribute("aria-label", responseWrap.title);
            responseWrap.textContent = "-";
        }

        block.appendChild(responseWrap);
    });
    return block;
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

function analysisForExercise(exercise) {
    if (exercise?.review_analysis && typeof exercise.review_analysis === "object") {
        return exercise.review_analysis;
    }
    return exercise?.analysis || {};
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
    if (analysis.recovery_softened === true) parts.push("recovered");
    if (analysis.ambiguous_lag === true) parts.push("lag?");
    return parts.length ? parts.join(", ") : "-";
}

function recognitionState(exercise) {
    const analysis = analysisForExercise(exercise);
    return analysis?.recognition_state || analysis?.band_state || "-";
}

function recognitionGear(exercise) {
    const analysis = analysisForExercise(exercise);
    const gear =
        analysis?.recognition_gear
        ?? analysis?.gear
        ?? exercise?.recognition_gear
        ?? exercise?.gear;
    return Number.isFinite(gear) ? gear : "-";
}

function buildSummaryRow(exercises) {
    const analysed = exercises.filter(
        (exercise) => analysisForExercise(exercise).has_evidence === true,
    );
    if (analysed.length === 0) return null;

    let correct = 0;
    let substitution = 0;
    let caught = 0;
    let miss = 0;
    let total = 0;

    analysed.forEach((exercise) => {
        const counts = countsForExercise(analysisForExercise(exercise));
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
        const analysis = analysisForExercise(exercise);
        const counts = countsForExercise(analysis);
        const row = document.createElement("tr");
        appendCell(row, exercise.index || idx + 1);
        appendCell(row, formatSymbolSequence(exercise.target));
        const heardCell = document.createElement("td");
        const heardBlock = buildRecognitionHeardBlock(record, exercise);
        if (heardBlock) {
            heardCell.appendChild(heardBlock);
        } else {
            heardCell.textContent = formatSymbolSequence(analysis.committed_answer);
        }
        row.appendChild(heardCell);
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

function detailTitle(record, { records }) {
    const parts = [formatStartedAt(record.started_at)];
    const sessionIndex = groupedSetIndex(record, records);
    const setIndex = record?.generation?.set_session ?? record?.set_session;
    if (Number.isInteger(sessionIndex) && Number.isInteger(setIndex)) {
        parts.push(`Session ${sessionIndex}`);
        parts.push(`Set ${setIndex} of 8`);
    } else if (Number.isInteger(sessionIndex)) {
        parts.push(`Session ${sessionIndex}`);
    } else if (Number.isInteger(setIndex)) {
        parts.push(`Set ${setIndex} of 8`);
    }
    return parts.join(" · ");
}

function groupedSetIndex(record, records) {
    const setId = record?.generation?.set_id ?? record?.set_id;
    if (!setId) return null;
    const groups = groupBySet(records).filter((group) => group.set_id);
    let sessionIndex = groups.length;
    for (const group of groups) {
        if (group.set_id === setId) return sessionIndex;
        sessionIndex -= 1;
    }
    return null;
}

function groupBySet(records) {
    const groups = [];
    let currentGroup = null;
    // Records arrive newest-first; sets group by set_id.
    records.forEach((rec) => {
        const id = rec.set_id || null;
        if (id && currentGroup && currentGroup.set_id === id) {
            currentGroup.records.push(rec);
        } else {
            currentGroup = { set_id: id, records: [rec] };
            groups.push(currentGroup);
        }
    });
    return groups;
}

function renderSetHeader(group, sessionIndex, { cssEscape }) {
    const row = document.createElement("tr");
    row.className = "settings-koch-set-header";
    row.dataset.setId = group.set_id;
    row.dataset.expanded = "false";
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.setAttribute("aria-expanded", "false");

    const cell = document.createElement("td");
    cell.colSpan = 5;
    const records = group.records;
    const total = records.length;
    const complete = total >= 8;
    const earliest = records[records.length - 1];
    const dateStr = formatStartedAt(earliest?.started_at);

    const arrow = document.createElement("span");
    arrow.className = "settings-koch-set-header__arrow";
    arrow.textContent = "▶";
    const label = document.createTextNode(
        ` Session ${sessionIndex} · ${total} of 8 sets${complete ? " · complete" : ""} · ${dateStr}`,
    );
    cell.append(arrow, label);
    row.appendChild(cell);

    const toggle = () => {
        const expanded = row.dataset.expanded === "true";
        row.dataset.expanded = expanded ? "false" : "true";
        row.setAttribute("aria-expanded", expanded ? "false" : "true");
        arrow.textContent = expanded ? "▶" : "▼";
        const rows = tbody.querySelectorAll(
            `tr[data-set-member="${cssEscape(group.set_id)}"]`,
        );
        rows.forEach((memberRow) => {
            memberRow.hidden = expanded;
        });
    };
    row.addEventListener("click", toggle);
    row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggle();
        }
    });
    return row;
}

function renderGroupedRows(records, { appendDeleteCell, attachRowHandler, cssEscape }) {
    const groups = groupBySet(records);
    let globalIdx = 0;
    let sessionIndex = groups.filter((group) => group.set_id).length;

    groups.forEach((group) => {
        if (group.set_id) {
            tbody.appendChild(renderSetHeader(group, sessionIndex, { cssEscape }));
            sessionIndex -= 1;
        }

        group.records.forEach((rec) => {
            globalIdx += 1;
            const row = document.createElement("tr");
            appendCell(row, globalIdx);
            appendCell(row, formatStartedAt(rec.started_at));
            appendCell(row, Array.isArray(rec.claimed_set) ? rec.claimed_set.join(" ") : "-");
            appendCell(row, rec.exercise_count ?? "-");
            appendDeleteCell(row, rec.filename);
            attachRowHandler(row, rec.filename);
            if (group.set_id) {
                row.dataset.setMember = group.set_id;
                row.hidden = true;
            }
            tbody.appendChild(row);
        });
    });
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
    listEndpoint: "/api/recognitions",
    recordEndpoint: "/api/recognition",
    deleteEndpoint: "/api/delete-recognition",
    changedKind: "recognition",
    dialogTitle: "Recognition session",
    loadingText: "Loading session...",
    emptyText: (data) =>
        `No saved recognition sessions in ${data.save_directory || "save directory"}.`,
    countText: (records, data) =>
        `${records.length} saved session${records.length === 1 ? "" : "s"} in ${data.save_directory}`,
    listErrorText: (err) => `Could not load saved recognition sessions: ${err.message}`,
    loadErrorText: (err) => `Could not load session: ${err.message}`,
    deleteConfirmText: "Delete this recognition session record?",
    deleteAriaLabel: "Delete recognition session record",
    deleteErrorText: (err) => `Could not delete recognition session: ${err.message}`,
    detailTitle,
    renderDetail,
    renderRows: renderGroupedRows,
});
