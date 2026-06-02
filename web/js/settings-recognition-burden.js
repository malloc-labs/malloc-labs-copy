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

function evidenceText(burden) {
    const evidence = Array.isArray(burden?.evidence) ? burden.evidence : [];
    if (evidence.length === 0) return "-";
    return evidence[0];
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
    ["Symbol", "Exposure", "Correct", "Fraction", "Miss", "Subst."].forEach((label) => {
        appendCell(header, "", label, "th");
    });
    thead.appendChild(header);
    table.appendChild(thead);

    const body = document.createElement("tbody");
    symbols.forEach((symbol) => {
        const row = document.createElement("tr");
        appendCell(row, "", symbol.symbol || "-");
        appendCell(row, "", String(symbol.exposures ?? 0));
        appendCell(row, "", String(symbol.correct ?? 0));
        appendCell(row, "", formatPercent(symbol.fraction));
        appendCell(row, "", String(symbol.misses ?? 0));
        appendCell(row, "", String(symbol.substitutions ?? 0));
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
    appendCell(row, "settings-recognition-burden__evidence", evidenceText(burden));
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
        `${claimed} · ${used} of ${total} records in the recent ` +
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
