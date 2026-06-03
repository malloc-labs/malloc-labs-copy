// Settings -> Koch Exercises tab: read-only burden debt summary.
//
// This is a presentational layer over /api/koch-band-evidence. It keeps
// the exercise surface free of scores while making the current practice
// burden profile inspectable after the listening act.

const root = document.getElementById("settings-koch-burden");
const meta = document.getElementById("settings-koch-burden-meta");
const tbody = document.getElementById("settings-koch-burden-tbody");

const STRONG_FRACTION = 0.95;
const LOW_FRACTION = 0.70;
const STRONG_STREAK_FOR_LOW_DEBT = 3;
const LOW_STREAK_FOR_HIGH_DEBT = 2;
const MEDIUM_CONFIDENCE_EVIDENCE = 2;
const HIGH_CONFIDENCE_EVIDENCE = 5;

const TOOLTIP_TEXT = {
    Burden: "The Koch exercise band. Higher bands carry heavier unit-length and stream-retention load.",
    Gear: "Current generated task gear for this band.",
    Debt: "Current unresolved instability estimate for this band. Low is settled; moderate/high needs service.",
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

function latestFraction(band) {
    const fractions = Array.isArray(band?.recent_fractions) ? band.recent_fractions : [];
    const value = Number(fractions[0]);
    return Number.isFinite(value) ? value : null;
}

function evidenceCount(band) {
    const fractions = Array.isArray(band?.recent_fractions) ? band.recent_fractions : [];
    return fractions.filter((value) => Number.isFinite(Number(value))).length;
}

function formatGear(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "-";
    return String(numeric);
}

function confidenceForBand(band) {
    const count = evidenceCount(band);
    if (count >= HIGH_CONFIDENCE_EVIDENCE) return "high";
    if (count >= MEDIUM_CONFIDENCE_EVIDENCE) return "medium";
    return "low";
}

function debtForBand(band) {
    const count = evidenceCount(band);
    if (count === 0) return "unknown";

    const latest = latestFraction(band);
    const strongStreak = Number(band?.strong_streak) || 0;
    const lowStreak = Number(band?.low_streak) || 0;
    const currentGear = Number(band?.current_gear);

    if (lowStreak >= LOW_STREAK_FOR_HIGH_DEBT) return "high";
    if (latest !== null && latest < LOW_FRACTION) return "high";
    if (strongStreak >= STRONG_STREAK_FOR_LOW_DEBT) return "low";
    if (latest !== null && latest >= STRONG_FRACTION && Number.isFinite(currentGear) && currentGear >= 3) {
        return "low";
    }
    return "moderate";
}

function evidenceText(band) {
    const latest = latestFraction(band);
    const latestText = latest === null ? "no recent fraction" : `latest ${latest.toFixed(3)}`;
    const strong = Number(band?.strong_streak) || 0;
    const low = Number(band?.low_streak) || 0;
    return `${latestText}; strong streak ${strong}; low streak ${low}`;
}

function renderHeaders() {
    const headers = root?.querySelectorAll("th") || [];
    headers.forEach((header) => addTooltip(header, TOOLTIP_TEXT[header.textContent]));
}

function renderBand(band) {
    const row = document.createElement("tr");
    row.className = "settings-recognition-burden__row";
    const debt = debtForBand(band);
    row.dataset.debt = debt;
    row.title = evidenceText(band);

    appendCell(row, "settings-koch-confusion__label", `Band ${band.burden_band ?? "-"}`);
    appendCell(row, "settings-koch-burden__gear", formatGear(band.current_gear));
    appendCell(row, "settings-recognition-burden__debt", debt);
    appendCell(row, "settings-recognition-burden__confidence", confidenceForBand(band));
    tbody.appendChild(row);
}

function renderProfile(profile) {
    const bands = Array.isArray(profile?.bands) ? profile.bands : [];
    tbody.replaceChildren();

    if (!bands.length || Number(profile?.sessions_used || 0) <= 0) {
        root.hidden = true;
        return;
    }

    const sessionsUsed = Number(profile.sessions_used) || 0;
    const totalSessions = Number(profile.session_count) || sessionsUsed;
    const windowSize = Number(profile.window_size) || sessionsUsed;
    const claimed = profile.claimed_set_key || "current set";
    meta.textContent =
        `${claimed} · band debt from ${sessionsUsed}/${totalSessions} session` +
        `${totalSessions === 1 ? "" : "s"} in the recent ${windowSize}-session evidence window`;

    bands.forEach((band) => renderBand(band));
    root.hidden = false;
}

async function loadBurdenProfile() {
    if (!root || !meta || !tbody) return;
    try {
        const res = await fetch("/api/koch-band-evidence", { cache: "no-store" });
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
