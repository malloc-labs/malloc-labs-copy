// Settings -> Koch Exercises tab: read-only practice-needs summary.
//
// This is a presentational layer over /api/koch-burden-profile. It keeps
// the exercise surface free of scores while making the current practice
// practice-needs profile inspectable after the listening act.

const root = document.getElementById("settings-koch-burden");
const meta = document.getElementById("settings-koch-burden-meta");
const tbody = document.getElementById("settings-koch-burden-tbody");
const detailDialog = document.getElementById("settings-koch-burden-dialog");
const detailTitle = document.getElementById("settings-koch-burden-dialog-title");
const detailBody = document.getElementById("settings-koch-burden-dialog-body");

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

const PROFILE_TOOLTIPS = {
    Area: "The part of practice being checked.",
    "Practice need": "How much this area still needs practice.",
    Confidence: "How sure the app is about that estimate.",
};

const BURDEN_META_TOOLTIPS = {
    "Practice need": "How much this area still needs practice.",
    Confidence: "How sure the app is about that estimate.",
    "Based on": "The observations behind this estimate.",
};

const BAND_TOOLTIPS = {
    Band: "The exercise group being tracked.",
    Average: "How often you copied this group correctly in recent practice.",
    Exercises: "How many recent exercises are included.",
    Gear: "The current difficulty step for this group.",
};

const MIXUP_TOOLTIPS = {
    Target: "The character that was played.",
    "Read as": "The character you entered instead.",
    Count: "How many times this mix-up has appeared.",
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

function evidenceCountText(burden) {
    const evidence = Array.isArray(burden?.evidence) ? burden.evidence : [];
    if (evidence.length === 1) return "1 item";
    return `${evidence.length} items`;
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

function appendBandTable(parent, burden) {
    const bands = Array.isArray(burden?.bands) ? burden.bands : [];
    if (!bands.length) return;

    const section = document.createElement("section");
    section.className = "settings-recognition-burden-detail__section";
    const heading = document.createElement("h3");
    heading.className = "settings-koch-detail__heading";
    heading.textContent = "Exercise groups";
    section.appendChild(heading);

    const table = document.createElement("table");
    table.className = "settings-recognition-burden-detail__table";
    const thead = document.createElement("thead");
    const header = document.createElement("tr");
    ["Band", "Average", "Exercises", "Gear"].forEach((label) => {
        const th = appendCell(header, "", label, "th");
        addTooltip(th, BAND_TOOLTIPS[label]);
    });
    thead.appendChild(header);
    table.appendChild(thead);

    const body = document.createElement("tbody");
    bands.forEach((band) => {
        const row = document.createElement("tr");
        appendCell(row, "", String(band.band ?? "-"));
        appendCell(row, "", formatPercent(band.average_fraction));
        appendCell(row, "", String(band.exercise_count ?? 0));
        appendCell(row, "", String(band.current_gear ?? "-"));
        body.appendChild(row);
    });
    table.appendChild(body);
    section.appendChild(table);
    parent.appendChild(section);
}

function appendMixupTable(parent, title, rows) {
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

function renderHeaders() {
    const headers = root?.querySelectorAll("th") || [];
    headers.forEach((header) => addTooltip(header, PROFILE_TOOLTIPS[header.textContent]));
}

function showBurdenDetail(key, burden) {
    if (!detailDialog || !detailTitle || !detailBody) return;
    detailTitle.textContent = `${formatKey(key)} practice need`;
    detailBody.replaceChildren();

    const metaGrid = document.createElement("dl");
    metaGrid.className = "settings-koch-detail__meta";
    [
        ["Practice need", formatDebt(burden?.debt)],
        ["Confidence", formatConfidence(burden?.confidence)],
        ["Based on", evidenceCountText(burden)],
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
    appendBandTable(detailBody, burden);
    appendMixupTable(detailBody, "Mix-ups", burden?.committed);
    detailDialog.showModal();
}

function renderBurden(key, burden) {
    const row = document.createElement("tr");
    row.className = "settings-recognition-burden__row";
    const debt = formatDebt(burden?.debt);
    row.dataset.debt = debt;
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
        `${claimed} · based on ${recordsUsed}/${totalRecords} saved session` +
        `${totalRecords === 1 ? "" : "s"} from the recent ${windowSize}-session window`;

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
