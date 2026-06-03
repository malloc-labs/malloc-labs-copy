// Settings -> Koch Exercises tab: read-only burden debt summary.
//
// This is a presentational layer over /api/koch-burden-profile. It keeps
// the exercise surface free of scores while making the current practice
// burden profile inspectable after the listening act.

const root = document.getElementById("settings-koch-burden");
const meta = document.getElementById("settings-koch-burden-meta");
const tbody = document.getElementById("settings-koch-burden-tbody");

const BURDEN_LABELS = {
    symbol_inventory: "Symbols",
    grouping: "Grouping",
    unit_length: "Unit length",
    confusion: "Confusions",
    signal: "Signal",
    rhythm: "Rhythm",
    anchor: "Anchor",
    practice_transfer: "Practice transfer",
};

const BURDEN_ORDER = [
    "symbol_inventory",
    "grouping",
    "unit_length",
    "confusion",
    "signal",
    "rhythm",
    "anchor",
    "practice_transfer",
];

const TOOLTIP_TEXT = {
    Burden: "The listening burden being estimated from Koch exercise evidence.",
    Debt: "Current unresolved instability estimate for this burden. Low is settled; moderate/high needs service.",
    Confidence: "How much recent evidence supports the debt estimate.",
};

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
    return evidence.join(" ");
}

function renderHeaders() {
    const headers = root?.querySelectorAll("th") || [];
    headers.forEach((header) => addTooltip(header, TOOLTIP_TEXT[header.textContent]));
}

function renderBurden(key, burden) {
    const row = document.createElement("tr");
    row.className = "settings-recognition-burden__row";
    const debt = formatDebt(burden?.debt);
    row.dataset.debt = debt;
    row.title = evidenceText(burden);

    appendCell(row, "settings-koch-confusion__label", formatKey(key));
    appendCell(row, "settings-recognition-burden__debt", debt);
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

    const recordsUsed = Number(profile.records_used) || 0;
    const totalRecords = Number(profile.record_count) || recordsUsed;
    const windowSize = Number(profile.window_size) || recordsUsed;
    const claimed = profile.claimed_set_key || "current set";
    meta.textContent =
        `${claimed} · burden debt from ${recordsUsed}/${totalRecords} session` +
        `${totalRecords === 1 ? "" : "s"} in the recent ${windowSize}-session evidence window`;

    keys.forEach((key) => renderBurden(key, burdens[key]));
    root.hidden = false;
}

async function loadBurdenProfile() {
    if (!root || !meta || !tbody) return;
    try {
        const res = await fetch("/api/koch-burden-profile", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        renderProfile(await res.json());
    } catch {
        tbody.replaceChildren();
        root.hidden = true;
    }
}

renderHeaders();
loadBurdenProfile();

window.addEventListener("copy-settings-records-changed", (event) => {
    if (event.detail?.kind === "koch") {
        loadBurdenProfile();
    }
});
