const root = document.getElementById("settings-koch-confusion");
const listEl = document.getElementById("settings-koch-confusion-list");

function renderPairs(data) {
    listEl.replaceChildren();
    const subs = Array.isArray(data.substitutions) ? data.substitutions : [];

    if (subs.length === 0) {
        root.hidden = true;
        return;
    }

    subs.forEach((pair) => {
        const li = document.createElement("li");
        li.className = "settings-koch-confusion__pair";
        const target = document.createElement("span");
        target.className = "settings-koch-confusion__symbol";
        target.textContent = pair.target;
        const arrow = document.createTextNode(" heard as ");
        const typed = document.createElement("span");
        typed.className = "settings-koch-confusion__symbol";
        typed.textContent = pair.typed;
        const count = document.createElement("span");
        count.className = "settings-koch-confusion__count";
        count.textContent = ` — ${pair.count}×`;
        li.append(target, arrow, typed, count);
        listEl.appendChild(li);
    });

    root.hidden = false;
}

async function loadConfusion() {
    try {
        const res = await fetch("/api/koch-confusion", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderPairs(data);
    } catch {
        root.hidden = true;
    }
}

loadConfusion();

window.addEventListener("copy-settings-records-changed", (event) => {
    if (event.detail?.kind === "koch") {
        loadConfusion();
    }
});
