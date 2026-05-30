// Settings page tab strip — App / Voice / Exercises.
//
// Always defaults to App on load; selection is not persisted across
// reloads (mirrors the timeline-tabs pattern in web/js/main.js).
// Tab switching toggles data-selected + aria-selected on the buttons
// and the `hidden` attribute on the panels.

const tabButtons = document.querySelectorAll(".settings-tab");
const panels = new Map();
tabButtons.forEach((btn) => {
    const panel = document.getElementById(btn.getAttribute("aria-controls"));
    if (panel) panels.set(btn.dataset.tab, panel);
});

function setActiveTab(name) {
    tabButtons.forEach((btn) => {
        const selected = btn.dataset.tab === name;
        btn.dataset.selected = selected ? "true" : "false";
        btn.setAttribute("aria-selected", selected ? "true" : "false");
    });
    panels.forEach((panel, key) => {
        panel.hidden = key !== name;
    });
}

tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => setActiveTab(btn.dataset.tab));
});

const tabShortcuts = new Map();
tabButtons.forEach((btn) => {
    const key = (btn.getAttribute("aria-keyshortcuts") || "").trim().toLowerCase();
    if (key) tabShortcuts.set(key, btn);
});

document.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target;
    if (target instanceof HTMLElement) {
        const tag = target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
    }
    const k = event.key.toLowerCase();
    const btn = tabShortcuts.get(k);
    if (btn) {
        event.preventDefault();
        btn.click();
    }
});

setActiveTab("app");
