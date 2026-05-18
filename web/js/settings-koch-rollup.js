// Settings page — recent band-evidence rollup.
//
// Fetches /api/koch-band-evidence and renders a small per-band panel
// above the saved sessions table. The panel is engine-side
// diagnostic: it shows what evidence the gear-up / gear-down rule
// will consume once it is wired in. Nothing here is shown on the
// listening surface; this is the surface for monitoring band and
// gear movement (engine spec §9 — no learner-facing progression
// metrics).
//
// The panel hides itself when there is no evidence yet (no saved
// answers for the most recent claimed set), so first-run setups stay
// quiet.

const root = document.getElementById("settings-koch-rollup");
const tbody = document.getElementById("settings-koch-rollup-tbody");
const metaEl = document.getElementById("settings-koch-rollup-meta");

const STRONG_FRACTION = 0.95;
const LOW_FRACTION = 0.70;

function classifyFraction(value) {
    if (!Number.isFinite(value)) return "missing";
    if (value >= STRONG_FRACTION) return "strong";
    if (value < LOW_FRACTION) return "low";
    return "building";
}

function formatFraction(value) {
    if (!Number.isFinite(value)) return "—";
    return value.toFixed(3);
}

function renderFractionList(fractions) {
    const wrap = document.createElement("span");
    wrap.className = "settings-koch-rollup__fractions";
    if (!Array.isArray(fractions) || fractions.length === 0) {
        wrap.textContent = "—";
        return wrap;
    }
    fractions.forEach((value, idx) => {
        const chip = document.createElement("span");
        chip.className = "settings-koch-rollup__chip";
        chip.dataset.state = classifyFraction(value);
        chip.textContent = formatFraction(value);
        wrap.appendChild(chip);
        if (idx < fractions.length - 1) {
            wrap.appendChild(document.createTextNode(" "));
        }
    });
    return wrap;
}

function renderBands(bands) {
    tbody.replaceChildren();
    bands.forEach((band) => {
        const tr = document.createElement("tr");

        const bandCell = document.createElement("td");
        bandCell.textContent = String(band.burden_band);
        tr.appendChild(bandCell);

        const fractionsCell = document.createElement("td");
        fractionsCell.appendChild(renderFractionList(band.recent_fractions));
        tr.appendChild(fractionsCell);

        const strongCell = document.createElement("td");
        strongCell.textContent = Number.isFinite(band.strong_streak)
            ? String(band.strong_streak)
            : "—";
        tr.appendChild(strongCell);

        const lowCell = document.createElement("td");
        lowCell.textContent = Number.isFinite(band.low_streak)
            ? String(band.low_streak)
            : "—";
        tr.appendChild(lowCell);

        tbody.appendChild(tr);
    });
}

async function loadRollup() {
    try {
        const res = await fetch("/api/koch-band-evidence", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const bands = Array.isArray(data.bands) ? data.bands : [];
        if (bands.length === 0 || !data.claimed_set_key) {
            root.hidden = true;
            return;
        }
        const key = data.claimed_set_key;
        const sessionsUsed = data.sessions_used ?? 0;
        const totalSessions = data.session_count ?? 0;
        const windowSize = data.window_size ?? sessionsUsed;
        metaEl.textContent =
            `${key} · last ${sessionsUsed}/${totalSessions} session` +
            `${totalSessions === 1 ? "" : "s"}` +
            ` (window ${windowSize})`;
        renderBands(bands);
        root.hidden = false;
    } catch (err) {
        // Diagnostic panel — failure here should not stop the rest of
        // the Koch tab from rendering. Hide quietly.
        root.hidden = true;
    }
}

loadRollup();
