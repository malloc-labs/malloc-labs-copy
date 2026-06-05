// Settings -> Recognition tab: read-only practice-needs profile.
//
// The profile is backend evidence, not a learner-facing score. It makes
// the first progression concept visible: areas with known practice needs,
// settled areas, and areas that still need probes before Copy should
// claim to understand them.

const root = document.getElementById("settings-recognition-burden");
const meta = document.getElementById("settings-recognition-burden-meta");
const tbody = document.getElementById("settings-recognition-burden-tbody");
const detailDialog = document.getElementById("settings-recognition-burden-dialog");
const detailTitle = document.getElementById("settings-recognition-burden-dialog-title");
const detailBody = document.getElementById("settings-recognition-burden-dialog-body");
const timeRoot = document.getElementById("settings-recognition-estimated-time");
const timeMeta = document.getElementById("settings-recognition-estimated-time-meta");
const timeTbody = document.getElementById("settings-recognition-estimated-time-tbody");

const BURDEN_LABELS = {
    symbol_inventory: "Symbols",
    unit_length: "Unit length",
    confusion: "Confusions",
    signal: "Listening conditions",
    rhythm: "Rhythm",
    anchor: "Anchor",
    practice_transfer: "Practice transfer",
};

const BURDEN_ORDER = [
    "symbol_inventory",
    "unit_length",
    "confusion",
    "signal",
    "rhythm",
    "anchor",
    "practice_transfer",
];

const KOCH_ORDER = [
    "K", "M", "U", "R", "E", "S", "N", "A", "P", "T",
    "L", "W", "I", ".", "J", "Z", "=", "F", "O", "Y",
    ",", "V", "G", "5", "/", "Q", "9", "2", "H", "3",
    "8", "B", "?", "4", "7", "C", "1", "D", "6", "0", "X",
];

const PROFILE_TOOLTIPS = {
    Area: "The part of practice being checked.",
    "Practice need": "How much this area still needs practice.",
    Confidence: "How sure the app is about that estimate.",
};

const SYMBOL_TOOLTIPS = {
    Symbol: "The character being tracked.",
    Introduced: "When this character first appeared in your saved practice.",
    Overall: "How often you have recognised this character correctly overall.",
    "Overall %": "Your overall recognition rate for this character. Arrow compares recent practice with overall performance.",
    Recent: "How often you recognised this character correctly in recent practice.",
    "Recent %": "Your recent recognition rate for this character.",
    Status: "Whether this character looks settled, improving, or needs more attention.",
    Miss: "Times you gave no answer for this character.",
    "Mix-ups": "Times this character was heard as another one, including near-misses you corrected.",
};

const BURDEN_META_TOOLTIPS = {
    "Practice need": "How much this area still needs practice.",
    Result: "The plain-language reading of the current evidence.",
    Confidence: "How sure the app is about that estimate.",
    "Based on": "The observations behind this estimate.",
};

const MIXUP_TOOLTIPS = {
    Target: "The character that was played.",
    "Read as": "The character you answered with instead.",
    Count: "How many times this mix-up has appeared.",
};

const ESTIMATE_TOOLTIPS = {
    Current: "The current state or next learning step.",
    Details: "The current score or estimated time left.",
    "Total time": "Total saved Recognition time if the estimate holds.",
};

function formatKey(value) {
    if (BURDEN_LABELS[value]) return BURDEN_LABELS[value];
    return String(value || "")
        .replace(/_/g, " ")
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatDebt(value) {
    if (value === "low") return "low";
    if (value === "moderate") return "moderate";
    if (value === "high") return "high";
    return "unknown";
}

function formatConfidence(value) {
    if (value === "high") return "high";
    if (value === "medium") return "medium";
    return "low";
}

function burdenKeys(burdens) {
    const known = new Set(Object.keys(burdens || {}));
    const ordered = BURDEN_ORDER.filter((key) => known.has(key));
    const extra = [...known].filter((key) => !BURDEN_ORDER.includes(key)).sort();
    return [...ordered, ...extra];
}

function evidenceCountText(burden) {
    const rhythmText = rhythmBasedOnText(burden);
    if (rhythmText) return rhythmText;
    const evidence = Array.isArray(burden?.evidence) ? burden.evidence : [];
    if (evidence.length === 1) return "1 item";
    return `${evidence.length} items`;
}

function metricExerciseCount(metric) {
    const count = Number(metric?.exercise_count);
    return Number.isFinite(count) && count >= 0 ? count : 0;
}

function rhythmBasedOnText(burden) {
    if (!burden || !("baseline" in burden || "probe" in burden)) return "";
    const baselineCount = metricExerciseCount(burden.baseline);
    const probeCount = metricExerciseCount(burden.probe);
    if (probeCount > 0) {
        return `${probeCount} rhythm probe exercises, ${baselineCount} baseline exercises`;
    }
    if (baselineCount > 0) {
        return `${baselineCount} baseline exercises`;
    }
    return "";
}

function rhythmVariationText(burden) {
    const evidence = Array.isArray(burden?.evidence) ? burden.evidence.join(" ") : "";
    const raised = evidence.match(/raised-cadence exercises \(variation ([^)]+)\)/);
    const baseline = evidence.match(/baseline exercises \(variation ([^)]+)\)/);
    if (raised && baseline) return `${baseline[1]} to ${raised[1]}`;
    const observed = evidence.match(/cadence variation ([^:]+):/);
    return observed ? observed[1] : "";
}

function rhythmResultText(burden) {
    if (!burden || !("baseline" in burden || "probe" in burden)) return "";
    const debt = formatDebt(burden.debt);
    const response = burden.response;
    const variation = rhythmVariationText(burden);
    if (response === "baseline_observed") {
        return variation
            ? `Stable at cadence variation ${variation}; higher variation not tested yet.`
            : "Stable at the current cadence variation; higher variation not tested yet.";
    }
    if (response === "needs_more_probe_evidence") {
        return "More rhythm probe samples are needed before this can be judged.";
    }
    if (response === "rhythm_hurt") {
        return variation
            ? `Rhythm needs support when cadence variation increases from ${variation}.`
            : "Rhythm needs support at the raised cadence variation.";
    }
    if (debt === "low") {
        return variation
            ? `No rhythm issue detected when cadence variation increased from ${variation}.`
            : "No rhythm issue detected at the raised cadence variation.";
    }
    return "Rhythm evidence has been collected, but the result is mixed.";
}

function burdenResultText(key, burden) {
    if (key === "rhythm") return rhythmResultText(burden);
    return "";
}

function rhythmMeaningText(burden) {
    if (!burden || !("baseline" in burden || "probe" in burden)) return "";
    if (burden.response === "baseline_observed") {
        return "Normal Recognition sessions show the current rhythm is usable, but this is not yet a raised-cadence probe.";
    }
    if (burden.response === "needs_more_probe_evidence") {
        return "Keep collecting normal sessions; the app needs a few more tagged rhythm probes before changing this estimate.";
    }
    if (burden.response === "rhythm_hurt") {
        return "Keep the symbol set stable and use gentle cadence variation before treating Rhythm as settled.";
    }
    if (formatDebt(burden.debt) === "low") {
        return "Keep normal progression. Collect more rhythm probes before treating higher cadence variation as settled.";
    }
    return "";
}

function appendMeaningSection(parent, key, burden) {
    const text = key === "rhythm" ? rhythmMeaningText(burden) : "";
    if (!text) return;
    const section = document.createElement("section");
    section.className = "settings-recognition-burden-detail__section";
    const heading = document.createElement("h3");
    heading.className = "settings-koch-detail__heading";
    heading.textContent = "What this means";
    const body = document.createElement("p");
    body.className = "settings-recognition-burden-detail__meaning";
    body.textContent = text;
    section.append(heading, body);
    parent.appendChild(section);
}

function appendCell(row, className, text, tagName = "td") {
    const cell = document.createElement(tagName);
    cell.className = className;
    cell.textContent = text;
    row.appendChild(cell);
    return cell;
}

function addTooltip(element, text) {
    if (!text) return;
    element.classList.add("settings-recognition-tooltip");
    element.dataset.tooltip = text;
    if (element.tabIndex < 0) {
        element.tabIndex = 0;
    }
}

function renderHeaders() {
    const headers = root?.querySelectorAll("th") || [];
    headers.forEach((header) => addTooltip(header, PROFILE_TOOLTIPS[header.textContent]));
    const estimateHeaders = timeRoot?.querySelectorAll("th") || [];
    estimateHeaders.forEach((header) => addTooltip(header, ESTIMATE_TOOLTIPS[header.textContent]));
}

function appendEvidenceList(parent, burden) {
    const evidence = Array.isArray(burden?.evidence) ? burden.evidence : [];
    const section = document.createElement("section");
    section.className = "settings-recognition-burden-detail__section";

    const heading = document.createElement("h3");
    heading.className = "settings-koch-detail__heading";
    heading.textContent = "What this is based on";
    section.appendChild(heading);

    if (evidence.length === 0) {
        const empty = document.createElement("p");
        empty.className = "settings-recognition-burden-detail__empty";
        empty.textContent = "No saved practice observations for this area yet.";
        section.appendChild(empty);
        parent.appendChild(section);
        return;
    }

    const list = document.createElement("ul");
    list.className = "settings-recognition-burden-detail__evidence";
    evidence.forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        list.appendChild(li);
    });
    section.appendChild(list);
    parent.appendChild(section);
}

function appendSymbolTable(parent, burden) {
    const symbols = Array.isArray(burden?.symbols) ? burden.symbols : [];
    if (!symbols.length) return;

    const section = document.createElement("section");
    section.className = "settings-recognition-burden-detail__section";
    const heading = document.createElement("h3");
    heading.className = "settings-koch-detail__heading";
    heading.textContent = "Symbols";
    section.appendChild(heading);

    const table = document.createElement("table");
    table.className = "settings-recognition-burden-detail__table";
    const thead = document.createElement("thead");
    const header = document.createElement("tr");
    [
        "Symbol",
        "Introduced",
        "Overall",
        "Overall %",
        "Recent",
        "Recent %",
        "Status",
        "Miss",
        "Mix-ups",
    ].forEach((label) => {
        const th = appendCell(header, "", label, "th");
        addTooltip(th, SYMBOL_TOOLTIPS[label]);
    });
    thead.appendChild(header);
    table.appendChild(thead);

    const body = document.createElement("tbody");
    symbols.forEach((symbol) => {
        const row = document.createElement("tr");
        appendCell(row, "", symbol.symbol || "-");
        appendCell(row, "", formatDate(symbol.introduced_at));
        appendCell(row, "", countPair(symbol.lifetime_correct, symbol.lifetime_exposures));
        appendOverallPercentCell(row, symbol);
        appendCell(row, "", countPair(symbol.recent_correct, symbol.recent_exposures));
        appendCell(row, "", formatPercent(symbol.recent_fraction));
        appendCell(row, `settings-recognition-burden-detail__signal`, symbol.signal || "-");
        appendCell(row, "", String(symbol.lifetime_misses ?? symbol.misses ?? 0));
        appendCell(
            row,
            "",
            String(symbol.lifetime_substitutions ?? symbol.substitutions ?? 0),
        );
        body.appendChild(row);
    });
    table.appendChild(body);
    section.appendChild(table);
    parent.appendChild(section);
}

function appendOverallPercentCell(row, symbol) {
    const cell = appendCell(row, "settings-recognition-burden-detail__overall-percent", "");
    const percent = document.createElement("span");
    percent.textContent = formatPercent(symbol?.lifetime_fraction);
    cell.appendChild(percent);

    const trend = symbolTrend(symbol);
    if (trend.value === "insufficient") return;

    const marker = document.createElement("span");
    marker.className = "settings-recognition-burden-detail__trend";
    marker.dataset.trend = trend.value;
    marker.textContent = trend.symbol;
    marker.title = trend.label;
    marker.setAttribute("aria-label", trend.label);
    cell.appendChild(marker);
    return cell;
}

function symbolTrend(symbol) {
    const lifetime = Number(symbol?.lifetime_fraction);
    const recent = Number(symbol?.recent_fraction);
    const recentExposures = Number(symbol?.recent_exposures);
    if (!Number.isFinite(lifetime) || !Number.isFinite(recent) || recentExposures <= 0) {
        return { value: "insufficient", symbol: "", label: "" };
    }

    const delta = recent - lifetime;
    if (delta >= 0.03) {
        return { value: "improving", symbol: "↑", label: "Recent trend improving" };
    }
    if (delta <= -0.03) {
        return { value: "worsening", symbol: "↓", label: "Recent trend down" };
    }
    return { value: "stable", symbol: "→", label: "Recent trend stable" };
}

function appendConfusionTable(parent, title, rows) {
    const pairs = Array.isArray(rows) ? rows : [];
    if (!pairs.length) return;

    const section = document.createElement("section");
    section.className = "settings-recognition-burden-detail__section";
    const heading = document.createElement("h3");
    heading.className = "settings-koch-detail__heading";
    heading.textContent = title;
    section.appendChild(heading);

    const table = document.createElement("table");
    table.className = "settings-recognition-burden-detail__table";
    const thead = document.createElement("thead");
    const header = document.createElement("tr");
    ["Target", "Read as", "Count"].forEach((label) => {
        const th = appendCell(header, "", label, "th");
        addTooltip(th, MIXUP_TOOLTIPS[label]);
    });
    thead.appendChild(header);
    table.appendChild(thead);

    const body = document.createElement("tbody");
    pairs.forEach((pair) => {
        const row = document.createElement("tr");
        appendCell(row, "", pair.target || "-");
        appendCell(row, "", pair.typed || "-");
        appendCell(row, "", String(pair.count ?? 0));
        body.appendChild(row);
    });
    table.appendChild(body);
    section.appendChild(table);
    parent.appendChild(section);
}

function formatPercent(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    return `${Math.round(numeric * 100)}%`;
}

function countPair(correct, total) {
    const correctNumber = Number(correct);
    const totalNumber = Number(total);
    if (!Number.isFinite(correctNumber) || !Number.isFinite(totalNumber) || totalNumber <= 0) {
        return "-";
    }
    return `${correctNumber}/${totalNumber}`;
}

function formatDate(value) {
    if (typeof value !== "string" || value.length === 0) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleDateString();
}

function formatDuration(seconds) {
    const numeric = Number(seconds);
    if (!Number.isFinite(numeric) || numeric < 0) return "-";
    const totalMinutes = Math.round(numeric / 60);
    if (totalMinutes < 60) return `${totalMinutes}m`;
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    if (minutes === 0) return `${hours}h`;
    return `${hours}h ${minutes}m`;
}

function formatSessions(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric < 0) return "-";
    const rounded = Math.round(numeric);
    return rounded === 1 ? "1 session" : `${rounded} sessions`;
}

function formatDurationRange(low, high) {
    const lowText = formatDuration(low);
    const highText = formatDuration(high);
    if (lowText === "-" && highText === "-") return "-";
    if (lowText === highText || highText === "-") return lowText;
    if (lowText === "-") return highText;
    return `${lowText}-${highText}`;
}

function prefixAbout(value) {
    if (!value || value === "-") return value;
    return `about ${value}`;
}

function formatSessionRange(low, high) {
    const lowNumber = Number(low);
    const highNumber = Number(high);
    if (!Number.isFinite(lowNumber) || !Number.isFinite(highNumber)) return "-";
    if (Math.round(lowNumber) === Math.round(highNumber)) return formatSessions(lowNumber);
    return `${Math.round(lowNumber)}-${Math.round(highNumber)} sessions`;
}

function estimateByKey(estimatedTime, key) {
    const estimates = Array.isArray(estimatedTime?.estimates) ? estimatedTime.estimates : [];
    return estimates.find((estimate) => estimate?.key === key) || null;
}

function nextKochAfter(claimedSetKey) {
    const claimed = new Set(String(claimedSetKey || "").split(/\s+/).filter(Boolean));
    return KOCH_ORDER.find((symbol) => !claimed.has(symbol)) || null;
}

function estimateDetail(estimate) {
    if (!estimate || estimate.status === "not_trending") {
        return "not clear yet";
    }
    if (estimate.status === "already_met") return "already there";
    return `${prefixAbout(formatDuration(estimate.seconds))} more`;
}

function estimateRangeDetail(estimate) {
    if (!estimate || estimate.status === "not_trending") {
        return "not clear yet";
    }
    const duration = formatDuration(estimate.seconds_high);
    return `${prefixAbout(duration)} more`;
}

function appendEstimateRow(label, estimateText, totalText, detail = "") {
    const row = document.createElement("tr");
    appendCell(row, "settings-koch-confusion__label", label);
    appendCell(row, "settings-recognition-estimated-time__estimate", estimateText);
    appendCell(row, "settings-recognition-estimated-time__total", totalText);
    if (detail) row.title = detail;
    timeTbody.appendChild(row);
}

function renderEstimatedTime(estimatedTime, claimedSetKey = "") {
    if (!timeRoot || !timeMeta || !timeTbody) return;
    timeTbody.replaceChildren();
    const current = estimatedTime?.current || {};
    const pace = estimatedTime?.pace || {};
    if (Number(current.sessions || 0) <= 0 || Number(current.practice_seconds || 0) <= 0) {
        timeRoot.hidden = true;
        return;
    }

    const aggregate = estimateByKey(estimatedTime, "aggregate_90_recent");
    const symbolsRange = estimateByKey(estimatedTime, "claimed_symbols_90_settled_range");
    const nextSymbol = estimatedTime?.next_symbol || nextKochAfter(claimedSetKey) || "-";

    const currentFraction = formatPercent(current.fraction);
    const paceText = formatDuration(pace.seconds_per_session);
    timeMeta.textContent =
        `You have ${formatDuration(current.practice_seconds)} saved across ${current.sessions} ` +
        `sessions. Recent sessions are taking about ${paceText}.`;

    appendEstimateRow(
        "Where am I now?",
        `${currentFraction} overall`,
        formatDuration(current.practice_seconds),
    );
    appendEstimateRow(
        "Estimated time to 90%",
        estimateDetail(aggregate),
        formatDuration(aggregate?.total_seconds),
        "Uses the recent Recognition accuracy as the future accuracy estimate.",
    );
    appendEstimateRow(
        `Next symbol: ${nextSymbol}`,
        estimateRangeDetail(symbolsRange),
        formatDuration(symbolsRange?.total_seconds_high),
        "Estimated time before all current claimed symbols are settled enough to add the next symbol.",
    );
    timeRoot.hidden = false;
}

function showBurdenDetail(key, burden) {
    if (!detailDialog || !detailTitle || !detailBody) return;
    detailTitle.textContent = `${formatKey(key)} practice need`;
    detailBody.replaceChildren();

    const metaGrid = document.createElement("dl");
    metaGrid.className = "settings-koch-detail__meta";
    const rows = [
        ["Practice need", formatDebt(burden?.debt)],
        ["Result", burdenResultText(key, burden)],
        ["Confidence", formatConfidence(burden?.confidence)],
        ["Based on", evidenceCountText(burden)],
    ].filter(([_label, value]) => value);
    rows.forEach(([label, value]) => {
        const dt = document.createElement("dt");
        dt.textContent = label;
        addTooltip(dt, BURDEN_META_TOOLTIPS[label]);
        const dd = document.createElement("dd");
        dd.textContent = value;
        metaGrid.append(dt, dd);
    });
    detailBody.appendChild(metaGrid);

    appendMeaningSection(detailBody, key, burden);
    appendEvidenceList(detailBody, burden);
    appendSymbolTable(detailBody, burden);
    appendConfusionTable(detailBody, "Committed mix-ups", burden?.committed);
    appendConfusionTable(detailBody, "Caught mix-ups", burden?.caught);
    detailDialog.showModal();
}

function renderBurden(key, burden) {
    const row = document.createElement("tr");
    row.className = "settings-recognition-burden__row";
    row.dataset.debt = formatDebt(burden?.debt);
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.setAttribute("aria-label", `Open ${formatKey(key)} practice need details`);
    row.addEventListener("click", () => showBurdenDetail(key, burden));
    row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            showBurdenDetail(key, burden);
        }
    });

    appendCell(row, "settings-koch-confusion__label", formatKey(key));
    appendCell(row, "settings-recognition-burden__debt", formatDebt(burden?.debt));
    appendCell(
        row,
        "settings-recognition-burden__confidence",
        formatConfidence(burden?.confidence),
    );
    tbody.appendChild(row);
}

function renderProfile(profile) {
    const burdens = profile?.burdens && typeof profile.burdens === "object"
        ? profile.burdens
        : {};
    const keys = burdenKeys(burdens);
    tbody.replaceChildren();

    if (!keys.length || Number(profile?.records_used || 0) <= 0) {
        root.hidden = true;
        renderEstimatedTime(null);
        return;
    }

    const used = Number(profile.records_used) || 0;
    const total = Number(profile.record_count) || used;
    const windowSize = Number(profile.window_size) || used;
    const claimed = profile.claimed_set_key || "current set";
    meta.textContent =
        `${claimed} · symbols use all saved practice since introduction; ` +
        `other areas use ${used} of ${total} records from the recent ` +
        `${windowSize}-record window`;

    keys.forEach((key) => renderBurden(key, burdens[key]));
    renderEstimatedTime(profile.estimated_time, profile.claimed_set_key);
    root.hidden = false;
}

async function loadBurdenProfile() {
    if (!root || !meta || !tbody) return;
    try {
        const res = await fetch("/api/recognition-burden-profile", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        renderProfile(await res.json());
    } catch {
        tbody.replaceChildren();
        root.hidden = true;
        renderEstimatedTime(null);
    }
}

renderHeaders();
loadBurdenProfile();

window.addEventListener("copy-settings-records-changed", (event) => {
    if (event.detail?.kind === "recognition") {
        loadBurdenProfile();
    }
});
