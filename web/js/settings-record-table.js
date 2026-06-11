import { appendCell } from "./settings-formatters.js";

function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
        return window.CSS.escape(value);
    }
    return value.replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

export function createRecordTableController(options) {
    const {
        tbody,
        metaEl,
        detailDialog,
        detailDialogTitle,
        detailDialogBody,
        prevButton,
        nextButton,
        countEl,
        listEndpoint,
        recordEndpoint,
        deleteEndpoint,
        changedKind,
        dialogTitle,
        loadingText,
        emptyText,
        countText,
        listErrorText,
        loadErrorText,
        deleteConfirmText,
        deleteAriaLabel,
        deleteErrorText,
        renderDetail,
        renderRowCells,
        detailTitle,
    } = options;

    let openFilename = null;
    let currentRecords = [];
    const detailCache = new Map();

    function rowForFilename(filename) {
        return tbody.querySelector(`tr[data-filename="${cssEscape(filename)}"]`);
    }

    function clearOpenDetail() {
        if (!openFilename) return;
        const prevRow = rowForFilename(openFilename);
        if (prevRow) {
            prevRow.dataset.expanded = "false";
            prevRow.setAttribute("aria-expanded", "false");
        }
        openFilename = null;
    }

    function updateNavButtons() {
        const idx = currentRecords.findIndex((rec) => rec.filename === openFilename);
        const hasOpenRecord = idx >= 0;
        if (prevButton) prevButton.disabled = !hasOpenRecord || idx === 0;
        if (nextButton) nextButton.disabled = !hasOpenRecord || idx === currentRecords.length - 1;
        if (countEl) {
            countEl.textContent = hasOpenRecord
                ? `${idx + 1} of ${currentRecords.length}`
                : `0 of ${currentRecords.length}`;
        }
    }

    async function loadRecord(filename) {
        if (detailCache.has(filename)) return detailCache.get(filename);
        const res = await fetch(`${recordEndpoint}?file=${encodeURIComponent(filename)}`, {
            cache: "no-store",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        detailCache.set(filename, data);
        return data;
    }

    async function deleteRecord(filename) {
        const res = await fetch(`${deleteEndpoint}?file=${encodeURIComponent(filename)}`, {
            cache: "no-store",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        detailCache.delete(filename);
        if (openFilename === filename) {
            detailDialog.close();
        }
        await loadSessions();
        window.dispatchEvent(new CustomEvent("copy-settings-records-changed", {
            detail: { kind: changedKind },
        }));
    }

    function openRecordByOffset(offset) {
        if (!openFilename || offset === 0) return;
        const idx = currentRecords.findIndex((rec) => rec.filename === openFilename);
        const nextRecord = currentRecords[idx + offset];
        if (!nextRecord) return;
        const row = rowForFilename(nextRecord.filename);
        if (row) {
            openDetail(nextRecord.filename, row);
        }
    }

    async function openDetail(filename, row) {
        clearOpenDetail();
        openFilename = filename;
        row.dataset.expanded = "true";
        row.setAttribute("aria-expanded", "true");
        detailDialogTitle.textContent = dialogTitle;
        detailDialogBody.textContent = loadingText;
        updateNavButtons();
        if (!detailDialog.open) detailDialog.showModal();
        try {
            const record = await loadRecord(filename);
            if (openFilename !== filename) return;
            detailDialogTitle.textContent = detailTitle(record);
            renderDetail(record);
            updateNavButtons();
        } catch (err) {
            detailDialogBody.textContent = loadErrorText(err);
            updateNavButtons();
        }
    }

    function attachRowHandler(row, filename) {
        row.classList.add("settings-koch-row");
        row.dataset.filename = filename;
        row.dataset.expanded = "false";
        row.setAttribute("role", "button");
        row.setAttribute("tabindex", "0");
        row.setAttribute("aria-expanded", "false");
        const toggle = () => {
            if (openFilename === filename) detailDialog.close();
            else openDetail(filename, row);
        };
        row.addEventListener("click", toggle);
        row.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                toggle();
            }
        });
    }

    function appendDeleteCell(row, filename) {
        const cell = document.createElement("td");
        cell.className = "settings-koch-table__delete-cell";
        const button = document.createElement("button");
        button.type = "button";
        button.className = "settings-koch-table__delete";
        button.textContent = "Delete";
        button.setAttribute("aria-label", deleteAriaLabel);
        button.addEventListener("click", async (event) => {
            event.stopPropagation();
            const ok = window.confirm(deleteConfirmText);
            if (!ok) return;
            try {
                button.disabled = true;
                await deleteRecord(filename);
            } catch (err) {
                button.disabled = false;
                window.alert(deleteErrorText(err));
            }
        });
        button.addEventListener("keydown", (event) => {
            event.stopPropagation();
        });
        cell.appendChild(button);
        row.appendChild(cell);
    }

    function renderRows(records) {
        tbody.replaceChildren();
        currentRecords = records;
        openFilename = null;
        updateNavButtons();
        records.forEach((rec, idx) => {
            const row = document.createElement("tr");
            renderRowCells(row, rec, idx, { appendCell });
            appendDeleteCell(row, rec.filename);
            attachRowHandler(row, rec.filename);
            tbody.appendChild(row);
        });
    }

    async function loadSessions() {
        try {
            const res = await fetch(listEndpoint, { cache: "no-store" });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const records = Array.isArray(data.records) ? data.records : [];
            if (records.length === 0) {
                metaEl.textContent = emptyText(data);
                currentRecords = [];
                openFilename = null;
                updateNavButtons();
                tbody.replaceChildren();
                return;
            }
            metaEl.textContent = countText(records, data);
            renderRows(records);
        } catch (err) {
            metaEl.textContent = listErrorText(err);
            currentRecords = [];
            openFilename = null;
            updateNavButtons();
            tbody.replaceChildren();
        }
    }

    if (tbody) loadSessions();

    detailDialog.addEventListener("close", () => {
        detailDialogTitle.textContent = dialogTitle;
        detailDialogBody.replaceChildren();
        clearOpenDetail();
        updateNavButtons();
    });

    detailDialog.addEventListener("click", (event) => {
        if (event.target === detailDialog) detailDialog.close();
    });

    prevButton?.addEventListener("click", () => openRecordByOffset(-1));
    nextButton?.addEventListener("click", () => openRecordByOffset(1));

    document.addEventListener("keydown", (event) => {
        if (!detailDialog.open || event.altKey || event.ctrlKey || event.metaKey) return;
        const key = event.key.toLowerCase();
        if (event.key === "ArrowLeft" || event.key === "<" || key === "h") {
            event.preventDefault();
            openRecordByOffset(-1);
        } else if (event.key === "ArrowRight" || event.key === ">" || key === "l") {
            event.preventDefault();
            openRecordByOffset(1);
        }
    });

    return { loadSessions };
}
