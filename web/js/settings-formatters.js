export function formatStartedAt(iso, fallback = "-") {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso || fallback;
    return d.toLocaleString();
}

export function formatDuration(startedIso, endedIso, fallback = "-") {
    const start = new Date(startedIso).getTime();
    const end = new Date(endedIso).getTime();
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return fallback;
    const totalSec = Math.round((end - start) / 1000);
    const mins = Math.floor(totalSec / 60);
    const secs = totalSec % 60;
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

export function appendCell(row, value) {
    const cell = document.createElement("td");
    cell.textContent = String(value);
    row.appendChild(cell);
}

export function fraction(value) {
    return Number.isFinite(value) ? value.toFixed(3) : "-";
}
