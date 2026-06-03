// Settings -> Koch Exercises tab: attention response summary.
//
// This section is separate from burden debt because signal texture may
// help attention instead of acting as a simple listening penalty.

const root = document.getElementById("settings-koch-attention");
const meta = document.getElementById("settings-koch-attention-meta");
const tbody = document.getElementById("settings-koch-attention-tbody");

const AXIS_ORDER = ["symbols", "grouping", "unit_length", "overall"];
const AXIS_LABELS = {
    symbols: "Symbols",
    grouping: "Grouping",
    unit_length: "Unit length",
    overall: "Overall",
};

const MAIN_HEADER_TOOLTIPS = {
    Condition: "Signal-condition grouping from saved Koch exercises.",
    Overall: "Combined copy response compared with the opposite S condition.",
    "S/T": "Observed RST Strength and Tone values.",
    Details: "Open per-axis values, deltas, and evidence.",
};

const DETAIL_HEADER_TOOLTIPS = {
    Axis: "Listening axis being compared.",
    Response: "Helped, neutral, hurt, mixed, or unknown against the opposite S condition.",
    Value: "Observed score for this condition.",
    Delta: "Difference from the opposite S condition.",
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

function renderHeaders() {
    const headers = root?.querySelectorAll("th") || [];
    headers.forEach((header) => addTooltip(header, MAIN_HEADER_TOOLTIPS[header.textContent]));
}

function appendHeader(row, text, tooltip) {
    const header = appendCell(row, "", text, "th");
    addTooltip(header, tooltip);
    return header;
}

function formatResponse(value) {
    if (value === "helped") return "helped";
    if (value === "neutral") return "neutral";
    if (value === "hurt") return "hurt";
    if (value === "mixed") return "mixed";
    return "unknown";
}

function evidenceText(condition) {
    const evidence = Array.isArray(condition?.evidence) ? condition.evidence : [];
    return evidence.join(" ");
}

function formatPercent(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "unknown";
    return `${Math.round(value * 1000) / 10}%`;
}

function formatDelta(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "-";
    const sign = value > 0 ? "+" : "";
    return `${sign}${formatPercent(value)}`;
}

function createDetailDialog(condition) {
    const dialog = document.createElement("dialog");
    dialog.className = "settings-koch-attention-dialog";

    const title = document.createElement("h3");
    title.className = "settings-koch-attention-dialog__title";
    title.textContent = condition?.label || "Attention response";
    dialog.appendChild(title);

    const metaLine = document.createElement("p");
    metaLine.className = "settings-recognition-burden__meta";
    metaLine.textContent =
        `${condition?.st_range || "unknown"} · ${Number(condition?.exercise_count || 0)} ` +
        `exercise${Number(condition?.exercise_count || 0) === 1 ? "" : "s"} · ` +
        `${condition?.confidence || "low"} confidence`;
    dialog.appendChild(metaLine);

    const table = document.createElement("table");
    table.className = "settings-recognition-burden-detail__table";
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    ["Axis", "Response", "Value", "Delta"].forEach((label) => {
        appendHeader(headerRow, label, DETAIL_HEADER_TOOLTIPS[label]);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);
    const detailBody = document.createElement("tbody");
    AXIS_ORDER.forEach((axis) => {
        const axisData = condition?.axes?.[axis] || {};
        const tr = document.createElement("tr");
        appendCell(tr, "settings-koch-confusion__label", AXIS_LABELS[axis] || axis);
        const response = formatResponse(axisData.response);
        const responseCell = appendCell(tr, "settings-koch-attention__response", response);
        responseCell.dataset.response = response;
        appendCell(tr, "settings-koch-attention__st", formatPercent(axisData.value));
        appendCell(tr, "settings-koch-attention__st", formatDelta(axisData.delta));
        detailBody.appendChild(tr);
    });
    table.appendChild(detailBody);
    dialog.appendChild(table);

    const evidence = document.createElement("p");
    evidence.className = "settings-koch-attention-dialog__evidence";
    evidence.textContent = evidenceText(condition);
    dialog.appendChild(evidence);

    const actions = document.createElement("div");
    actions.className = "settings-koch-attention-dialog__actions";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "btn";
    close.textContent = "Close";
    close.addEventListener("click", () => dialog.close());
    actions.appendChild(close);
    dialog.appendChild(actions);

    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) dialog.close();
    });
    return dialog;
}

function openConditionDetails(condition) {
    const dialog = createDetailDialog(condition);
    document.body.appendChild(dialog);
    dialog.addEventListener("close", () => dialog.remove(), { once: true });
    dialog.showModal();
}

function renderCondition(condition) {
    const row = document.createElement("tr");
    row.className = "settings-koch-attention__row";
    row.title = evidenceText(condition);

    appendCell(row, "settings-koch-confusion__label", condition?.label || "Condition");
    const response = formatResponse(condition?.axes?.overall?.response);
    const responseCell = appendCell(row, "settings-koch-attention__response", response);
    responseCell.dataset.response = response;
    appendCell(row, "settings-koch-attention__st", condition?.st_range || "unknown");
    const actionCell = appendCell(row, "settings-koch-attention__action", "");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "settings-koch-attention__details";
    button.textContent = "View";
    button.addEventListener("click", () => openConditionDetails(condition));
    actionCell.appendChild(button);
    tbody.appendChild(row);
}

function usefulConditions(conditions) {
    return conditions.filter((condition) => Number(condition?.exercise_count || 0) > 0);
}

function renderProfile(profile) {
    const conditions = usefulConditions(
        Array.isArray(profile?.conditions) ? profile.conditions : [],
    );
    tbody.replaceChildren();

    if (!conditions.length || Number(profile?.exercise_count || 0) <= 0) {
        root.hidden = true;
        return;
    }

    const recordsUsed = Number(profile.records_used) || 0;
    const exerciseCount = Number(profile.exercise_count) || 0;
    const windowSize = Number(profile.window_size) || recordsUsed;
    const claimed = profile.claimed_set_key || "current set";
    meta.textContent =
        `${claimed} · ${exerciseCount} S/T-tagged exercise` +
        `${exerciseCount === 1 ? "" : "s"} in the recent ${windowSize}-session window`;

    conditions.forEach((condition) => renderCondition(condition));
    root.hidden = false;
}

async function loadAttentionResponse() {
    if (!root || !meta || !tbody) return;
    try {
        const res = await fetch("/api/koch-attention-response", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        renderProfile(await res.json());
    } catch {
        tbody.replaceChildren();
        root.hidden = true;
    }
}

renderHeaders();
loadAttentionResponse();

window.addEventListener("copy-settings-records-changed", (event) => {
    if (event.detail?.kind === "koch") {
        loadAttentionResponse();
    }
});
