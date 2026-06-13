// Rhythm baseline renderer shared by Cadence and Freeplay reviews.
//
// Builds a single exercise block: one column per character, plus narrow
// word-gap separator columns between words. Each char column carries
// asymmetric green|amber|red zones and any attempt markers stacked
// underneath. Attempt markers position themselves at an x-fraction
// relative to the column's *baseline-expected* leading gap, so a
// perfectly-timed send lands at x=0 and an overshoot rises into amber
// and red. ditMs is the source of truth for the ideal gap math
// (character gap = 3 dits, word gap = 7 dits).
//
// Pure DOM — no module state, no event listeners. The caller is
// responsible for re-invoking on state changes.

// Span over the ideal gap that the attempt marker can travel within a
// column. ~3x ideal lands at the right edge of red; perceptual mapping,
// not a hard tolerance.
const X_SPAN_RATIO = 3.0;
const INLINE_DENSITIES = ["normal", "compact", "dense", "micro"];

let rhythmReviewResizeObserver = null;
let rhythmReviewPresentationWired = false;
let currentRhythmReviewDetail = null;

export function buildExerciseBlock({ exercise, title, ariaLabel, events, ditMs }) {
    const charGapMs = 3 * ditMs;
    const wordGapMs = 7 * ditMs;

    const block = document.createElement("section");
    block.className = "key-rhythm-baseline__exercise";
    if (ariaLabel) block.setAttribute("aria-label", ariaLabel);

    if (title) {
        const labelEl = document.createElement("p");
        labelEl.className = "key-rhythm-baseline__exercise-label";
        labelEl.textContent = title;
        block.appendChild(labelEl);
    }

    const colsEl = document.createElement("div");
    colsEl.className = "key-rhythm-baseline__cols";

    const charCols = [];
    const wordGapCols = [];
    // Per char column: the baseline-expected leading gap type that an
    // on-time send would produce. "none" for the first symbol; "word"
    // for the first symbol of each subsequent word; "character" for
    // in-word symbols.
    const charColExpected = [];

    const buildZonesEl = () => {
        const zonesEl = document.createElement("div");
        zonesEl.className = "key-rhythm-baseline__zones";
        zonesEl.setAttribute("aria-hidden", "true");
        ["green", "amber", "red"].forEach((zone) => {
            const cell = document.createElement("span");
            cell.className = `key-rhythm-baseline__zone key-rhythm-baseline__zone--${zone}`;
            zonesEl.appendChild(cell);
        });
        return zonesEl;
    };

    const buildEmptyZonesEl = () => {
        const zonesEl = document.createElement("div");
        zonesEl.className = "key-rhythm-baseline__zones";
        return zonesEl;
    };

    const appendCharCol = (symbol) => {
        const col = document.createElement("div");
        col.className = "key-rhythm-baseline__col key-rhythm-baseline__col--char";

        const symEl = document.createElement("span");
        symEl.className = "key-rhythm-baseline__symbol";
        symEl.textContent = symbol;

        col.append(symEl, buildZonesEl());
        colsEl.appendChild(col);
        charCols.push(col);
    };

    const appendWordGapCol = () => {
        const col = document.createElement("div");
        col.className = "key-rhythm-baseline__col key-rhythm-baseline__col--word-gap";
        col.setAttribute("aria-hidden", "true");

        // Placeholder children keep the row vertical alignment.
        const symEl = document.createElement("span");
        symEl.className = "key-rhythm-baseline__symbol";
        symEl.textContent = " ";

        col.append(symEl, buildEmptyZonesEl());
        colsEl.appendChild(col);
        wordGapCols.push(col);
    };

    const words = exercise.split(" ").filter((word) => word.length > 0);
    words.forEach((word, wordIdx) => {
        if (wordIdx > 0) appendWordGapCol();
        for (let i = 0; i < word.length; i++) {
            let expected;
            if (charCols.length === 0) expected = "none";
            else if (i === 0) expected = "word";
            else expected = "character";
            appendCharCol(word[i]);
            charColExpected.push(expected);
        }
    });
    block.dataset.columns = String(charCols.length + wordGapCols.length);

    // Segment events into attempt rows. Each event flagged
    // isAttemptStart begins a new row; subsequent events fill the row
    // left-to-right until the next start (or until the columns run
    // out). Events keyed before any attempt-start land in an implicit
    // first row.
    if (charCols.length > 0) {
        const attempts = [];
        events.forEach((evt) => {
            if (evt.isAttemptStart || attempts.length === 0) {
                attempts.push([]);
            }
            attempts[attempts.length - 1].push(evt);
        });

        attempts.forEach((attempt, attemptIdx) => {
            for (let colIdx = 0; colIdx < charCols.length; colIdx++) {
                const col = charCols[colIdx];
                const attemptEl = document.createElement("div");
                attemptEl.className = "key-rhythm-baseline__attempt";
                const evt = attempt[colIdx];
                if (evt) {
                    const expected = charColExpected[colIdx];
                    const idealMs = expected === "word" ? wordGapMs : charGapMs;
                    const gapMs = Number(evt.leadingGapMs);
                    let xFrac = 0;
                    if (expected !== "none" && Number.isFinite(gapMs) && idealMs > 0) {
                        const overshootRatio = Math.max(0, (gapMs - idealMs) / idealMs);
                        xFrac = Math.min(1, overshootRatio / X_SPAN_RATIO);
                    }
                    const markerEl = document.createElement("div");
                    markerEl.className = "key-rhythm-baseline__attempt-marker";
                    markerEl.style.setProperty("--attempt-x", String(xFrac));
                    const arrowEl = document.createElement("span");
                    arrowEl.className = "key-rhythm-baseline__attempt-arrow";
                    arrowEl.setAttribute("aria-hidden", "true");
                    arrowEl.textContent = "↑";
                    const sentEl = document.createElement("span");
                    sentEl.className = "key-rhythm-baseline__attempt-symbol";
                    sentEl.textContent = evt.symbol;
                    markerEl.append(arrowEl, sentEl);
                    attemptEl.append(markerEl);
                }
                col.appendChild(attemptEl);
            }
            // After every second attempt (and not after the final
            // one), redraw the baseline bar so the next two attempts
            // have a fresh reference instead of stacking into a
            // waterfall.
            const isLastAttempt = attemptIdx === attempts.length - 1;
            if ((attemptIdx + 1) % 2 === 0 && !isLastAttempt) {
                charCols.forEach((col) => col.appendChild(buildZonesEl()));
                wordGapCols.forEach((col) => col.appendChild(buildEmptyZonesEl()));
            }
        });
    }

    block.appendChild(colsEl);
    return block;
}

// Builds the per-character "expected leading gap" steps for an exercise
// string ("none" / "word" / "character"). Used by both renderers and by
// attempt-tracking state walkers.
export function buildExpectedSteps(exercise) {
    const steps = [];
    const words = (exercise || "").split(" ");
    words.forEach((word, wordIdx) => {
        for (let i = 0; i < word.length; i++) {
            const leading = wordIdx === 0 && i === 0
                ? "none"
                : i === 0
                ? "word"
                : "character";
            steps.push({ symbol: word[i], leading });
        }
    });
    return steps;
}

export function syncRhythmReviewPresentation(renderDetail) {
    const symbolsEl = document.getElementById("key-rhythm-review-symbols");
    const expandEl = document.getElementById("key-rhythm-review-expand");
    const dialogEl = document.getElementById("key-rhythm-review-dialog");
    const dialogTitleEl = document.getElementById("key-rhythm-review-dialog-title");
    const dialogBodyEl = document.getElementById("key-rhythm-review-dialog-body");
    const dialogCloseEl = document.getElementById("key-rhythm-review-dialog-close");
    if (!symbolsEl || !expandEl || !dialogEl || !dialogTitleEl || !dialogBodyEl) return;

    currentRhythmReviewDetail = renderDetail;
    wireRhythmReviewPresentation({
        symbolsEl,
        expandEl,
        dialogEl,
        dialogTitleEl,
        dialogBodyEl,
        dialogCloseEl,
    });
    queueRhythmReviewLayout(symbolsEl, expandEl);
}

function wireRhythmReviewPresentation({
    symbolsEl,
    expandEl,
    dialogEl,
    dialogTitleEl,
    dialogBodyEl,
    dialogCloseEl,
}) {
    if (!rhythmReviewResizeObserver) {
        rhythmReviewResizeObserver = new ResizeObserver(() => {
            const currentSymbolsEl = document.getElementById("key-rhythm-review-symbols");
            const currentExpandEl = document.getElementById("key-rhythm-review-expand");
            if (currentSymbolsEl && currentExpandEl) {
                queueRhythmReviewLayout(currentSymbolsEl, currentExpandEl);
            }
        });
    }
    rhythmReviewResizeObserver.observe(symbolsEl);

    if (rhythmReviewPresentationWired) return;
    rhythmReviewPresentationWired = true;

    expandEl.addEventListener("click", () => {
        if (!currentRhythmReviewDetail) return;
        const detail = currentRhythmReviewDetail();
        if (!detail || !detail.content) return;
        dialogTitleEl.textContent = detail.title || "Rhythm review";
        dialogBodyEl.replaceChildren(detail.content);
        if (!dialogEl.open) dialogEl.showModal();
    });
    if (dialogCloseEl) {
        dialogCloseEl.addEventListener("click", () => dialogEl.close());
    }
    dialogEl.addEventListener("click", (event) => {
        if (event.target === dialogEl) dialogEl.close();
    });
}

function queueRhythmReviewLayout(symbolsEl, expandEl) {
    window.requestAnimationFrame(() => applyRhythmReviewLayout(symbolsEl, expandEl));
}

function applyRhythmReviewLayout(symbolsEl, expandEl) {
    const block = symbolsEl.querySelector(".key-rhythm-baseline__exercise");
    if (!block) {
        symbolsEl.removeAttribute("data-density");
        delete symbolsEl.dataset.inline;
        delete symbolsEl.dataset.overflowing;
        expandEl.hidden = true;
        return;
    }

    const maxWidth = symbolsEl.clientWidth;
    if (maxWidth <= 0) return;

    symbolsEl.dataset.inline = "true";
    let selectedDensity = INLINE_DENSITIES[0];
    let overflow = false;

    for (const density of INLINE_DENSITIES) {
        symbolsEl.dataset.density = density;
        const contentWidth = rhythmReviewContentWidth(symbolsEl);
        selectedDensity = density;
        overflow = contentWidth > maxWidth + 1;
        if (!overflow) break;
    }

    symbolsEl.dataset.density = selectedDensity;
    symbolsEl.dataset.overflowing = overflow ? "true" : "false";
    expandEl.hidden = selectedDensity === "normal" && !overflow;
}

function rhythmReviewContentWidth(symbolsEl) {
    const widths = [...symbolsEl.querySelectorAll(".key-rhythm-baseline__exercise")]
        .map((block) => block.scrollWidth);
    return widths.length ? Math.max(...widths) : 0;
}
