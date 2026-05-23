// Settings page — Copy > Key lifetime view modal.

const dialog = document.getElementById("settings-copy-key-lifetime-dialog");
const titleEl = document.getElementById("settings-copy-key-lifetime-title");
const body = document.getElementById("settings-copy-key-lifetime-body");
const link = document.getElementById("settings-copy-key-history-link");

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
    return value.toFixed(2);
}

function formatStartedAt(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
}

function buildGearChangesSection(events) {
    const section = document.createElement("section");
    section.className = "settings-koch-lifetime__section";
    const heading = document.createElement("h3");
    heading.className = "settings-koch-lifetime__heading";
    heading.textContent = "Gear changes";
    section.appendChild(heading);

    if (!Array.isArray(events) || events.length === 0) {
        const empty = document.createElement("p");
        empty.className = "settings-koch-lifetime__empty";
        empty.textContent = "No gear changes yet.";
        section.appendChild(empty);
        return section;
    }

    const list = document.createElement("ol");
    list.className = "settings-koch-lifetime__changes";
    [...events].reverse().forEach((event) => {
        const li = document.createElement("li");
        const direction = event.current_gear > event.previous_gear ? "↑" : "↓";
        const when = formatStartedAt(event.started_at);
        li.textContent =
            `Session ${event.run_index} (${when}) · band ${event.burden_band}: ` +
            `gear ${event.previous_gear} → ${event.current_gear} ${direction}`;
        list.appendChild(li);
    });
    section.appendChild(list);
    return section;
}

function buildCurrentGearsSection(currentGears, claimedSetKey) {
    const section = document.createElement("section");
    section.className = "settings-koch-lifetime__section";
    const heading = document.createElement("h3");
    heading.className = "settings-koch-lifetime__heading";
    heading.textContent = "Current gears";
    section.appendChild(heading);

    const line = document.createElement("p");
    line.className = "settings-koch-lifetime__current";
    const indices = Object.keys(currentGears || {})
        .map((k) => Number(k))
        .filter((k) => Number.isFinite(k))
        .sort((a, b) => a - b);
    if (indices.length === 0) {
        line.textContent = `${claimedSetKey || "—"} · no resolved gears yet`;
    } else {
        const tokens = indices.map((idx) => `band ${idx} → gear ${currentGears[idx]}`);
        line.textContent = `${claimedSetKey || "—"} · ${tokens.join(" · ")}`;
    }
    section.appendChild(line);
    return section;
}

function buildHistoryGridSection(history) {
    const section = document.createElement("section");
    section.className = "settings-koch-lifetime__section";
    const heading = document.createElement("h3");
    heading.className = "settings-koch-lifetime__heading";
    heading.textContent = "Per-band history (newest right)";
    section.appendChild(heading);

    const sessions = Array.isArray(history.sessions) ? history.sessions : [];
    const bands = Array.isArray(history.bands) ? history.bands : [];
    if (sessions.length === 0 || bands.length === 0) {
        const empty = document.createElement("p");
        empty.className = "settings-koch-lifetime__empty";
        empty.textContent = "No saved history yet.";
        section.appendChild(empty);
        return section;
    }

    const wrap = document.createElement("div");
    wrap.className = "settings-koch-lifetime__grid-wrap";
    const table = document.createElement("table");
    table.className = "settings-koch-lifetime__grid";

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    const corner = document.createElement("th");
    corner.scope = "col";
    corner.className = "settings-koch-lifetime__band-col";
    corner.textContent = "Band";
    headRow.appendChild(corner);
    sessions.forEach((session) => {
        const th = document.createElement("th");
        th.scope = "col";
        th.textContent = `S${session.run_index}`;
        th.title = formatStartedAt(session.started_at);
        headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    bands.forEach((band) => {
        const tr = document.createElement("tr");
        const label = document.createElement("th");
        label.scope = "row";
        label.className = "settings-koch-lifetime__band-col";
        label.textContent = String(band.burden_band);
        tr.appendChild(label);

        const byRun = new Map();
        (band.entries || []).forEach((entry) => byRun.set(entry.run_index, entry));
        let prevGear = null;
        sessions.forEach((session) => {
            const cell = document.createElement("td");
            const entry = byRun.get(session.run_index);
            if (!entry) {
                cell.textContent = "—";
                cell.classList.add("settings-koch-lifetime__cell--missing");
                tr.appendChild(cell);
                return;
            }
            cell.dataset.state = classifyFraction(entry.fraction);
            cell.dataset.gear = String(entry.gear ?? 0);
            if (prevGear !== null && entry.gear !== prevGear) {
                cell.classList.add("settings-koch-lifetime__cell--gear-change");
            }
            const fractionSpan = document.createElement("span");
            fractionSpan.className = "settings-koch-lifetime__fraction";
            fractionSpan.textContent = formatFraction(entry.fraction);
            const gearSpan = document.createElement("span");
            gearSpan.className = "settings-koch-lifetime__gear";
            gearSpan.textContent = `g${entry.gear ?? 0}`;
            cell.append(fractionSpan, gearSpan);
            prevGear = entry.gear;
            tr.appendChild(cell);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    section.appendChild(wrap);
    return section;
}

function render(history) {
    body.replaceChildren();
    body.appendChild(buildGearChangesSection(history.gear_changes));
    body.appendChild(buildCurrentGearsSection(history.current_gears, history.claimed_set_key));
    body.appendChild(buildHistoryGridSection(history));
}

async function loadHistory(claimedSetKey) {
    const url = claimedSetKey
        ? `/api/copy-key-band-history?claimed_set_key=${encodeURIComponent(claimedSetKey)}`
        : "/api/copy-key-band-history";
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function openLifetime() {
    const key = link.dataset.claimedSetKey || "";
    titleEl.textContent = key ? `Lifetime · ${key}` : "Lifetime";
    body.textContent = "Loading lifetime history…";
    if (!dialog.open) dialog.showModal();
    try {
        const history = await loadHistory(key);
        const count = history.session_count ?? 0;
        titleEl.textContent =
            `Lifetime · ${history.claimed_set_key || key || "—"} · ` +
            `${count} session${count === 1 ? "" : "s"}`;
        render(history);
    } catch (err) {
        body.textContent = `Could not load lifetime history: ${err.message}`;
    }
}

if (link) link.addEventListener("click", openLifetime);

dialog.addEventListener("close", () => {
    body.replaceChildren();
    titleEl.textContent = "Lifetime";
});

dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
});
