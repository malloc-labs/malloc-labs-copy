// Settings page — practice calendars.
//
// Renders one calendar widget per saved-sessions tab (Koch and Key/Send)
// as a per-day at-a-glance of practice activity. Same component, two
// instances: each is parameterised by the DOM root and the listing
// endpoint. Day cells show the claimed-set in effect at the end of that
// day plus the total exercises taken across all sessions on that day —
// useful for judging whether the next-symbol nudge is firing at
// sensible moments.
//
// Aggregation rules for days with multiple sessions:
//   • claimed_set: the latest session's set (the state the learner
//     ended the day on — most informative for nudge tuning).
//   • exercise_count: sum across all sessions that day.
//   • duration_seconds: sum of (ended_at − started_at) across all
//     sessions that day, displayed as rounded minutes.
//   • cumulative_seconds: per-claimed-set running total, in seconds.
//     Each session attributes its duration to its own claimed_set
//     (so transition-day sessions split correctly into their
//     respective set buckets), and the day's stored value is the
//     running total for the set the day's *last* session was on —
//     which by construction matches the day's stored claimed_set.
//     This resets visibly on a set transition, which is the
//     intent: the right-column number answers "how much time on
//     this exact set so far?"
//
// Data sources: /api/koch-exercises and /api/cadence-sends. Both return
// the same shape (started_at, ended_at, claimed_set, exercise_count).
// The earliest navigable month is 2026-01.

const MIN_YEAR = 2026;
const MIN_MONTH = 0; // January

const MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
];

function localDateKey(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

// Wall-clock seconds between two ISO timestamps. Returns 0 if either
// is missing/invalid or if ended_at precedes started_at (clock skew or
// a record written before the engine populated ended_at).
function sessionDurationSeconds(started_at, ended_at) {
    if (typeof started_at !== "string" || typeof ended_at !== "string") return 0;
    const start = new Date(started_at).getTime();
    const end = new Date(ended_at).getTime();
    if (Number.isNaN(start) || Number.isNaN(end) || end <= start) return 0;
    return (end - start) / 1000;
}

function formatPracticeMinutes(seconds) {
    if (!seconds || seconds <= 0) return "";
    const minutes = Math.max(1, Math.round(seconds / 60));
    return `${minutes}m`;
}

function mountCalendar({ root, endpoint, emptyLabel }) {
    if (!root) return;
    const titleEl = root.querySelector("[data-calendar-title]");
    const metaEl = root.querySelector("[data-calendar-meta]");
    const gridEl = root.querySelector("[data-calendar-grid]");
    const prevBtn = root.querySelector("[data-calendar-prev]");
    const nextBtn = root.querySelector("[data-calendar-next]");
    if (!titleEl || !metaEl || !gridEl || !prevBtn || !nextBtn) return;

    const today = new Date();
    let viewYear = Math.max(today.getFullYear(), MIN_YEAR);
    let viewMonth = viewYear === today.getFullYear() ? today.getMonth() : MIN_MONTH;

    // Map<YYYY-MM-DD, {claimed_set, exercise_count, duration_seconds}>
    // in local time so calendar squares match the wall clock the
    // learner saw when they were practising.
    const practiceDays = new Map();

    function isAtMinMonth() {
        return viewYear === MIN_YEAR && viewMonth === MIN_MONTH;
    }

    function stepMonth(delta) {
        let m = viewMonth + delta;
        let y = viewYear;
        while (m < 0) { m += 12; y -= 1; }
        while (m > 11) { m -= 12; y += 1; }
        if (y < MIN_YEAR || (y === MIN_YEAR && m < MIN_MONTH)) return;
        viewYear = y;
        viewMonth = m;
        render();
    }

    function render() {
        titleEl.textContent = `${MONTH_NAMES[viewMonth]} ${viewYear}`;
        prevBtn.disabled = isAtMinMonth();

        const first = new Date(viewYear, viewMonth, 1);
        // JS getDay: 0=Sun..6=Sat. Convert to Mon=0..Sun=6.
        const leading = (first.getDay() + 6) % 7;
        const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
        const todayKey = localDateKey(today);

        gridEl.replaceChildren();

        for (let i = 0; i < leading; i += 1) {
            const blank = document.createElement("div");
            blank.className = "settings-calendar__day settings-calendar__day--blank";
            blank.setAttribute("aria-hidden", "true");
            gridEl.appendChild(blank);
        }

        for (let d = 1; d <= daysInMonth; d += 1) {
            const cell = document.createElement("div");
            cell.className = "settings-calendar__day";
            cell.setAttribute("role", "gridcell");

            const key = `${viewYear}-${String(viewMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
            const entry = practiceDays.get(key);
            if (entry) {
                cell.dataset.practice = "true";
                const claimed = entry.claimed_set.join(" ");
                const minutesLabel = formatPracticeMinutes(entry.duration_seconds);
                const durationLabel = minutesLabel ? `, ${minutesLabel} of practice` : "";
                const cumulativeLabel = formatPracticeMinutes(entry.cumulative_seconds);
                const cumulativeAria = cumulativeLabel
                    ? `, ${cumulativeLabel} cumulative on ${claimed || "this set"}`
                    : "";
                cell.setAttribute(
                    "aria-label",
                    `${d} ${MONTH_NAMES[viewMonth]} — claimed ${claimed || "none"}, ${entry.exercise_count} exercise${entry.exercise_count === 1 ? "" : "s"}${durationLabel}${cumulativeAria}`,
                );
            } else {
                cell.setAttribute("aria-label", `${d} ${MONTH_NAMES[viewMonth]}`);
            }
            if (key === todayKey) cell.dataset.today = "true";

            const num = document.createElement("span");
            num.className = "settings-calendar__day-num";
            num.textContent = String(d);
            cell.appendChild(num);

            if (entry) {
                const claimed = document.createElement("span");
                claimed.className = "settings-calendar__day-claimed";
                claimed.textContent = entry.claimed_set.join(" ");
                cell.appendChild(claimed);

                const count = document.createElement("span");
                count.className = "settings-calendar__day-count";
                count.textContent = `${entry.exercise_count} ex`;
                cell.appendChild(count);

                // Bottom row pairs the day's minutes (left) with the
                // per-claimed-set running total (right). The cumulative
                // is rendered as secondary context (lighter weight); on
                // the first day of a new set it equals the day's
                // minutes, which is intentional — it marks the start of
                // a fresh per-set counter.
                const footer = document.createElement("div");
                footer.className = "settings-calendar__day-footer";

                const minutesLabel = formatPracticeMinutes(entry.duration_seconds);
                const duration = document.createElement("span");
                duration.className = "settings-calendar__day-duration";
                duration.textContent = minutesLabel;
                footer.appendChild(duration);

                const cumulativeLabel = formatPracticeMinutes(entry.cumulative_seconds);
                const cumulative = document.createElement("span");
                cumulative.className = "settings-calendar__day-cumulative";
                cumulative.textContent = cumulativeLabel;
                footer.appendChild(cumulative);

                cell.appendChild(footer);
            }

            gridEl.appendChild(cell);
        }
    }

    async function loadSessions() {
        try {
            const res = await fetch(endpoint, { cache: "no-store" });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const records = Array.isArray(data.records) ? data.records : [];
            practiceDays.clear();
            // Both listing endpoints return newest-first. Walk oldest
            // first so the final claimed_set kept per day is the
            // latest session's, and per-set running totals accumulate
            // in chronological order.
            const oldestFirst = [...records].reverse();
            // setKey ("K M U" sorted) -> total seconds across all
            // sessions on that exact set, walked forward in time.
            const setRunningTotal = new Map();
            oldestFirst.forEach((rec) => {
                const d = new Date(rec.started_at);
                if (Number.isNaN(d.getTime())) return;
                const key = localDateKey(d);
                const prev = practiceDays.get(key);
                const count = Number.isFinite(rec.exercise_count) ? rec.exercise_count : 0;
                const claimed = Array.isArray(rec.claimed_set) ? rec.claimed_set : [];
                const duration = sessionDurationSeconds(rec.started_at, rec.ended_at);
                const setKey = [...claimed].sort().join(" ");
                const setTotal = (setRunningTotal.get(setKey) || 0) + duration;
                setRunningTotal.set(setKey, setTotal);
                practiceDays.set(key, {
                    claimed_set: claimed,
                    exercise_count: (prev?.exercise_count || 0) + count,
                    duration_seconds: (prev?.duration_seconds || 0) + duration,
                    cumulative_seconds: setTotal,
                });
            });
            if (records.length === 0) {
                metaEl.textContent = `No ${emptyLabel} in ${data.save_directory || "save directory"}.`;
            } else {
                metaEl.textContent = `${practiceDays.size} day${practiceDays.size === 1 ? "" : "s"} with practice across ${records.length} session${records.length === 1 ? "" : "s"}.`;
            }
        } catch (err) {
            metaEl.textContent = `Could not load saved sessions: ${err.message}`;
        }
        render();
    }

    prevBtn.addEventListener("click", () => stepMonth(-1));
    nextBtn.addEventListener("click", () => stepMonth(1));

    // If this calendar lives inside a popup dialog, refresh from the
    // server every time the dialog is opened. Without this, the
    // calendar's snapshot is whatever was fetched at page load and a
    // session run since then does not appear until the page is
    // reloaded.
    const containingDialog = root.closest("dialog");
    if (containingDialog?.id) {
        const selector = `[data-calendar-open="${CSS.escape(containingDialog.id)}"]`;
        document.querySelectorAll(selector).forEach((trigger) => {
            trigger.addEventListener("click", () => {
                loadSessions();
            });
        });
    }

    render();
    loadSessions();
}

mountCalendar({
    root: document.getElementById("settings-koch-calendar"),
    endpoint: "/api/koch-exercises",
    emptyLabel: "saved Koch sessions",
});

mountCalendar({
    root: document.getElementById("settings-key-calendar"),
    endpoint: "/api/cadence-sends",
    emptyLabel: "saved send sessions",
});

mountCalendar({
    root: document.getElementById("settings-copy-key-calendar"),
    endpoint: "/api/copy-key-sessions",
    emptyLabel: "saved copy > key sessions",
});

mountCalendar({
    root: document.getElementById("settings-recognition-calendar"),
    endpoint: "/api/recognitions",
    emptyLabel: "saved recognition sessions",
});

// Wire each [data-calendar-open="<dialog-id>"] trigger to showModal()
// the matching <dialog>. Clicking the backdrop closes the dialog —
// matches the existing settings-koch-lifetime dialog behaviour.
document.querySelectorAll("[data-calendar-open]").forEach((trigger) => {
    const dialog = document.getElementById(trigger.dataset.calendarOpen);
    if (!dialog) return;
    trigger.addEventListener("click", () => {
        if (!dialog.open) dialog.showModal();
    });
    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) dialog.close();
    });
});
