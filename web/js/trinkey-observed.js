// Rolling readout of the dit duration the Trinkey is actually
// emitting, derived from the engine's `key-event` release measurements.
//
// Persisted to localStorage so the Settings page can show the last
// observed value even if it was not open during keying. The Settings
// page subscribes via the `storage` event for cross-tab updates and
// reads the snapshot on init.
//
// We track the median (not the mean) of a small rolling window so the
// readout is robust against single outlier dits without smoothing over
// real speed changes — e.g. a Vail-driven CC1 will land in the window
// within a few elements and the median will flip.

const STORAGE_KEY = "copy-653:trinkey-observed";
const SAME_TAB_EVENT = "copy-653:trinkey-observed-changed";
const WINDOW_SIZE = 12;

function safeGetStorage() {
    try {
        return window.localStorage;
    } catch {
        return null;
    }
}

function readSnapshot() {
    const storage = safeGetStorage();
    if (!storage) return null;
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return null;
    try {
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object") return null;
        if (!Number.isFinite(parsed.ditMs) || parsed.ditMs <= 0) return null;
        if (!Array.isArray(parsed.window)) return null;
        if (typeof parsed.observedAt !== "number") return null;
        return parsed;
    } catch {
        return null;
    }
}

function median(values) {
    const sorted = [...values].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    if (sorted.length % 2 === 0) {
        return (sorted[mid - 1] + sorted[mid]) / 2;
    }
    return sorted[mid];
}

function writeSnapshot(snapshot) {
    const storage = safeGetStorage();
    if (!storage) return;
    storage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
    // localStorage's `storage` event only fires in other documents.
    // Same-tab subscribers (e.g. the Key page header indicator that
    // observes the very dits being recorded) need a separate signal.
    window.dispatchEvent(new CustomEvent(SAME_TAB_EVENT));
}

export function recordObservedDit(durationMs) {
    if (!Number.isFinite(durationMs) || durationMs <= 0) return;
    const previous = readSnapshot();
    const window = previous?.window ?? [];
    window.push(durationMs);
    while (window.length > WINDOW_SIZE) window.shift();
    const ditMs = median(window);
    writeSnapshot({
        ditMs,
        window,
        observedAt: Date.now(),
    });
}

export function getObservedDit() {
    const snapshot = readSnapshot();
    if (!snapshot) return null;
    return {
        ditMs: snapshot.ditMs,
        wpm: 1200 / snapshot.ditMs,
        observedAt: snapshot.observedAt,
    };
}

export function subscribeObservedDit(callback) {
    const storageHandler = (event) => {
        if (event.key !== STORAGE_KEY) return;
        callback(getObservedDit());
    };
    const sameTabHandler = () => callback(getObservedDit());
    window.addEventListener("storage", storageHandler);
    window.addEventListener(SAME_TAB_EVENT, sameTabHandler);
    return () => {
        window.removeEventListener("storage", storageHandler);
        window.removeEventListener(SAME_TAB_EVENT, sameTabHandler);
    };
}

export function clearObservedDit() {
    const storage = safeGetStorage();
    if (!storage) return;
    storage.removeItem(STORAGE_KEY);
}
