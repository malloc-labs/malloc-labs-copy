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
