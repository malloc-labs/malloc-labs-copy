// Settings page — recent Send Cadence evidence rollup.
//
// Mirrors the Koch diagnostic split: backend evidence is visible in
// Settings, not on the practice surface.

const root = document.getElementById("settings-key-rollup");
const tbody = document.getElementById("settings-key-rollup-tbody");
const metaEl = document.getElementById("settings-key-rollup-meta");

const STRONG_FRACTION = 0.95;
const LOW_FRACTION = 0.70;

function classifyFraction(value) {
    if (!Number.isFinite(value)) return "missing";
    if (value >= STRONG_FRACTION) return "strong";
    if (value < LOW_FRACTION) return "low";
    return "building";
}

function formatFraction(value) {
    if (!Number.isFinite(value)) return "-";
    return value.toFixed(3);
}

function renderFractionList(fractions) {
    const wrap = document.createElement("span");
    wrap.className = "settings-koch-rollup__fractions";
    if (!Array.isArray(fractions) || fractions.length === 0) {
        wrap.textContent = "-";
        return wrap;
    }
    fractions.forEach((value, idx) => {
        const chip = document.createElement("span");
        chip.className = "settings-koch-rollup__chip";
        chip.dataset.state = classifyFraction(value);
        chip.textContent = formatFraction(value);
        wrap.appendChild(chip);
        if (idx < fractions.length - 1) wrap.appendChild(document.createTextNode(" "));
    });
    return wrap;
}

function appendCell(row, value) {
    const cell = document.createElement("td");
    cell.textContent = String(value);
    row.appendChild(cell);
}

const METRIC_FIELDS = [
    ["Sym", "symbol_fraction"],
    ["Spc", "spacing_fraction"],
    ["Frm", "formation_fraction"],
    ["Gap", "gap_timing_fraction"],
];

function renderMetricStrip(band) {
    const wrap = document.createElement("span");
    wrap.className = "settings-key-rollup__metrics";
    METRIC_FIELDS.forEach(([label, key]) => {
        const item = document.createElement("span");
        item.className = "settings-key-rollup__metric";
        const labelEl = document.createElement("span");
        labelEl.className = "settings-key-rollup__metric-label";
        labelEl.textContent = label;
        const valueEl = document.createElement("span");
        valueEl.textContent = formatFraction(band[key]);
        item.appendChild(labelEl);
        item.appendChild(valueEl);
        wrap.appendChild(item);
    });
    return wrap;
}

function renderBands(bands) {
    tbody.replaceChildren();
    bands.forEach((band) => {
        const tr = document.createElement("tr");
        appendCell(tr, band.burden_band);
        const fractionsCell = document.createElement("td");
        fractionsCell.appendChild(renderFractionList(band.recent_fractions));
        tr.appendChild(fractionsCell);
        const metricsCell = document.createElement("td");
        metricsCell.appendChild(renderMetricStrip(band));
        tr.appendChild(metricsCell);
        appendCell(tr, Number.isFinite(band.strong_streak) ? band.strong_streak : "-");
        appendCell(tr, Number.isFinite(band.low_streak) ? band.low_streak : "-");
        tbody.appendChild(tr);
    });
}

async function loadRollup() {
    try {
        const res = await fetch("/api/cadence-band-evidence", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const bands = Array.isArray(data.bands) ? data.bands : [];
        if (bands.length === 0 || !data.claimed_set_key) {
            root.hidden = true;
            return;
        }
        const sessionsUsed = data.sessions_used ?? 0;
        const totalSessions = data.session_count ?? 0;
        metaEl.textContent =
            `${data.claimed_set_key} · last ${sessionsUsed}/${totalSessions} session` +
            `${totalSessions === 1 ? "" : "s"}`;
        renderBands(bands);
        root.hidden = false;
    } catch {
        root.hidden = true;
    }
}

if (root) loadRollup();
