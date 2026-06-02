// Settings -> Recognition tab: read-only burden debt profile.
//
// The profile is backend evidence, not a learner-facing score. It makes
// the first progression concept visible: burdens with known debt, burdens
// with low debt, and burdens that still need probes before Copy should
// claim to understand them.

const root = document.getElementById("settings-recognition-burden");
const meta = document.getElementById("settings-recognition-burden-meta");
const tbody = document.getElementById("settings-recognition-burden-tbody");
const detailDialog = document.getElementById("settings-recognition-burden-dialog");
const detailTitle = document.getElementById("settings-recognition-burden-dialog-title");
const detailBody = document.getElementById("settings-recognition-burden-dialog-body");

const BURDEN_LABELS = {
    symbol_inventory: "Symbols",
    unit_length: "Unit length",
    confusion: "Confusions",
    signal: "Signal",
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

const SYMBOL_TOOLTIPS = {
    Symbol: "The target Morse symbol being evaluated.",
    Introduced: "First saved recognition record where this symbol appears as analysed evidence.",
    Lifetime: "Correct recognitions over all exposures since the symbol was introduced.",
    "Lifetime %": "Lifetime recognition fraction since introduction.",
    Recent: "Correct recognitions over exposures in the current recent evidence window.",
    "Recent %": "Recent recognition fraction for the current evidence window.",
    Signal: "Conservative comparison of lifetime and recent evidence: stable, watch, recovering, fragile, or undersampled.",
    Miss: "Lifetime windows where no symbol was heard for this target.",
    "Subst.": "Lifetime substitutions and caught substitutions for this target.",
};

const BURDEN_META_TOOLTIPS = {
    Debt: "Current burden debt estimate. Low is settled; moderate/high means this burden needs attention.",
    Confidence: "How much evidence supports the debt estimate.",
    Evidence: "Number of evidence statements listed below for this burden.",
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
    const evidence = Array.isArray(burden?.evidence) ? burden.evidence : [];
    if (evidence.length === 1) return "1 item";
    return `${evidence.length} items`;
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

function appendEvidenceList(parent, burden) {
    const evidence = Array.isArray(burden?.evidence) ? burden.evidence : [];
    const section = document.createElement("section");
    section.className = "settings-recognition-burden-detail__section";

    const heading = document.createElement("h3");
    heading.className = "settings-koch-detail__heading";
    heading.textContent = "Evidence";
    section.appendChild(heading);

    if (evidence.length === 0) {
        const empty = document.createElement("p");
        empty.className = "settings-recognition-burden-detail__empty";
        empty.textContent = "No evidence recorded for this burden yet.";
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
        "Lifetime",
        "Lifetime %",
        "Recent",
        "Recent %",
        "Signal",
        "Miss",
        "Subst.",
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
        appendCell(row, "", formatPercent(symbol.lifetime_fraction));
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
    ["Target", "Read as", "Count"].forEach((label) => appendCell(header, "", label, "th"));
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

function showBurdenDetail(key, burden) {
    if (!detailDialog || !detailTitle || !detailBody) return;
    detailTitle.textContent = `${formatKey(key)} burden`;
    detailBody.replaceChildren();

    const metaGrid = document.createElement("dl");
    metaGrid.className = "settings-koch-detail__meta";
    [
        ["Debt", formatDebt(burden?.debt)],
        ["Confidence", formatConfidence(burden?.confidence)],
        ["Evidence", evidenceCountText(burden)],
    ].forEach(([label, value]) => {
        const dt = document.createElement("dt");
        dt.textContent = label;
        addTooltip(dt, BURDEN_META_TOOLTIPS[label]);
        const dd = document.createElement("dd");
        dd.textContent = value;
        metaGrid.append(dt, dd);
    });
    detailBody.appendChild(metaGrid);

    appendEvidenceList(detailBody, burden);
    appendSymbolTable(detailBody, burden);
    appendConfusionTable(detailBody, "Committed confusions", burden?.committed);
    appendConfusionTable(detailBody, "Caught confusions", burden?.caught);
    detailDialog.showModal();
}

function renderBurden(key, burden) {
    const row = document.createElement("tr");
    row.className = "settings-recognition-burden__row";
    row.dataset.debt = formatDebt(burden?.debt);
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.setAttribute("aria-label", `Open ${formatKey(key)} burden details`);
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
        return;
    }

    const used = Number(profile.records_used) || 0;
    const total = Number(profile.record_count) || used;
    const windowSize = Number(profile.window_size) || used;
    const claimed = profile.claimed_set_key || "current set";
    meta.textContent =
        `${claimed} · symbols measured since introduction; ` +
        `other burdens use ${used} of ${total} records in the recent ` +
        `${windowSize}-record evidence window`;

    keys.forEach((key) => renderBurden(key, burdens[key]));
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
    }
}

loadBurdenProfile();

window.addEventListener("copy-settings-records-changed", (event) => {
    if (event.detail?.kind === "recognition") {
        loadBurdenProfile();
    }
});
