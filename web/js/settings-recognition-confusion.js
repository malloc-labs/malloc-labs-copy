// Settings → Recognition tab: per-symbol confusion from saved Symbol
// Recognition sessions.
//
// Reads /api/recognition-confusion, which returns two streams derived
// from the per-exercise analysis blocks (recognition_analysis):
//
//   committed_substitutions — truth → what the learner committed
//   caught_substitutions     — truth → a false start they superseded
//                              before committing (self-correction)
//
// The streams are rendered as two separate sections and never merged: a
// caught confusion is evidence the discrimination is forming, not a
// committed error. Percentages are trend evidence for the Settings view,
// not in-session scoring or feedback.

const committedRoot = document.getElementById("settings-recognition-committed");
const committedList = document.getElementById("settings-recognition-committed-list");
const caughtRoot = document.getElementById("settings-recognition-caught");
const caughtList = document.getElementById("settings-recognition-caught-list");
const timingRoot = document.getElementById("settings-recognition-timing");
const timingList = document.getElementById("settings-recognition-timing-list");
const meta = document.getElementById("settings-recognition-meta");

// A committed substitution must recur before it reads as a pattern
// (mirrors the Koch panel's cutoff). A caught self-correction is rarer
// and more interesting, so it surfaces sooner.
const COMMITTED_MIN = 4;
const CAUGHT_MIN = 2;
const TIMING_MIN = 2;

function formatRate(value, total) {
    if (!Number.isFinite(value) || total <= 0) return "—";
    return `${Math.round(value * 100)}%`;
}

function formatTrend(value) {
    if (value === "improving") return "improving";
    if (value === "worsening") return "worsening";
    if (value === "stable") return "stable";
    return "not enough data";
}

function formatTimingTrend(value) {
    if (value === "improving") return "faster";
    if (value === "worsening") return "slower";
    if (value === "stable") return "stable";
    return "limited";
}

function formatDuration(ms) {
    if (!Number.isFinite(ms)) return "—";
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
}

function renderStream(root, listEl, pairs, minCount, connector) {
    listEl.replaceChildren();
    const shown = (Array.isArray(pairs) ? pairs : []).filter((p) => p.count >= minCount);
    if (shown.length === 0) {
        root.hidden = true;
        return;
    }
    const header = document.createElement("li");
    header.className = "settings-koch-confusion__pair settings-koch-confusion__pair--header";
    ["Pair", "Recent", "Previous", "Trend", "Total"].forEach((label) => {
        const cell = document.createElement("span");
        cell.textContent = label;
        header.appendChild(cell);
    });
    listEl.appendChild(header);
    shown.forEach((pair) => {
        const li = document.createElement("li");
        li.className = "settings-koch-confusion__pair";
        const pairLabel = document.createElement("span");
        pairLabel.className = "settings-koch-confusion__label";
        const target = document.createElement("span");
        target.className = "settings-koch-confusion__symbol";
        target.textContent = pair.target;
        const typed = document.createElement("span");
        typed.className = "settings-koch-confusion__symbol";
        typed.textContent = pair.typed;
        pairLabel.append(target, document.createTextNode(connector), typed);

        const recent = document.createElement("span");
        recent.className = "settings-koch-confusion__rate";
        recent.textContent = formatRate(pair.recent_rate, pair.recent_total);
        recent.title = `${pair.recent_count || 0} of ${pair.recent_total || 0} recent target exposures`;

        const previous = document.createElement("span");
        previous.className = "settings-koch-confusion__previous";
        previous.textContent = formatRate(pair.previous_rate, pair.previous_total);
        previous.title = `${pair.previous_count || 0} of ${pair.previous_total || 0} previous target exposures`;

        const trend = document.createElement("span");
        trend.className = "settings-koch-confusion__trend";
        trend.dataset.trend = pair.trend || "insufficient";
        trend.textContent = formatTrend(pair.trend);

        const count = document.createElement("span");
        count.className = "settings-koch-confusion__count";
        count.textContent = `${pair.count}×`;
        count.title = "Lifetime count";
        li.append(pairLabel, recent, previous, trend, count);
        listEl.appendChild(li);
    });
    root.hidden = false;
}

function renderTiming(rows) {
    if (!timingRoot || !timingList) return;
    timingList.replaceChildren();
    const shown = (Array.isArray(rows) ? rows : []).filter((row) => row.count >= TIMING_MIN);
    if (shown.length === 0) {
        timingRoot.hidden = true;
        return;
    }

    const header = document.createElement("li");
    header.className = "settings-koch-confusion__pair settings-koch-confusion__pair--header";
    ["Unit", "Recent", "Previous", "Trend", "Total"].forEach((label) => {
        const cell = document.createElement("span");
        cell.textContent = label;
        header.appendChild(cell);
    });
    timingList.appendChild(header);

    shown.forEach((row) => {
        const li = document.createElement("li");
        li.className = "settings-koch-confusion__pair";
        li.title = [
            `${row.correct_count || 0} exact`,
            `${row.confused_count || 0} confused`,
            `${row.missed_count || 0} missed`,
            `${row.late_count || 0} late`,
        ].join(" · ");

        const target = document.createElement("span");
        target.className = "settings-koch-confusion__label";
        const gear = document.createElement("span");
        gear.className = "settings-koch-confusion__symbol";
        gear.textContent = `G${row.gear}`;
        const word = document.createElement("span");
        word.className = "settings-koch-confusion__symbol";
        word.textContent = row.target;
        target.append(gear, document.createTextNode(" "), word);

        const recent = document.createElement("span");
        recent.className = "settings-koch-confusion__rate";
        recent.textContent = formatDuration(row.recent_median_ms);
        recent.title = `${row.recent_count || 0} recent attempts`;

        const previous = document.createElement("span");
        previous.className = "settings-koch-confusion__previous";
        previous.textContent = formatDuration(row.previous_median_ms);
        previous.title = `${row.previous_count || 0} previous attempts`;

        const trend = document.createElement("span");
        trend.className = "settings-koch-confusion__trend";
        trend.dataset.trend = row.trend || "insufficient";
        trend.textContent = formatTimingTrend(row.trend);

        const total = document.createElement("span");
        total.className = "settings-koch-confusion__count";
        total.textContent = `${row.count}×`;
        total.title = `Lifetime median ${formatDuration(row.median_ms)}`;

        li.append(target, recent, previous, trend, total);
        timingList.appendChild(li);
    });
    timingRoot.hidden = false;
}

function updateMeta(exercisesUsed) {
    if (exercisesUsed === 0) {
        meta.textContent = "No saved recognition sessions yet.";
        return;
    }
    const noun = exercisesUsed === 1 ? "exercise" : "exercises";
    const anyShown = !committedRoot.hidden || !caughtRoot.hidden;
    meta.textContent = anyShown
        ? `${exercisesUsed} ${noun} with evidence`
        : `${exercisesUsed} ${noun} analysed — no recurring confusions yet.`;
}

async function loadConfusion() {
    try {
        const res = await fetch("/api/recognition-confusion", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderStream(committedRoot, committedList, data.committed_substitutions, COMMITTED_MIN,
            " heard as ");
        renderStream(caughtRoot, caughtList, data.caught_substitutions, CAUGHT_MIN,
            " nearly read as ");
        updateMeta(Number(data.exercises_used) || 0);
    } catch {
        committedRoot.hidden = true;
        caughtRoot.hidden = true;
        meta.textContent = "Could not load recognition sessions.";
    }
}

async function loadTiming() {
    if (!timingRoot || !timingList) return;
    try {
        const res = await fetch("/api/recognition-timing", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderTiming(data.targets);
    } catch {
        timingRoot.hidden = true;
    }
}

loadConfusion();
loadTiming();

window.addEventListener("copy-settings-records-changed", (event) => {
    if (event.detail?.kind === "recognition") {
        loadConfusion();
        loadTiming();
    }
});
