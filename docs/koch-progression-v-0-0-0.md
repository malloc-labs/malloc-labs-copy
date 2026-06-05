# Koch Progression for Controlled Auditory Acquisition Without Symbol Collapse

Version 0.0.0

## 1 Problem Statement

The Koch method is directionally correct: introduce Morse symbols as auditory
shapes, keep the active symbol set small, and train at a real character speed
from the beginning. The weakness is not Koch itself. The weakness is the
community shorthand that has grown around it.

In common practice, Koch progression is often reduced to a rule such as:

> Move to the next character when accuracy reaches 90%.

This is under-specified. It collapses several different claims into one number:

- 90% of which symbol set size?
- 90% of which symbols?
- 90% over how many exposures?
- 90% over how much listening time?
- 90% at isolated-symbol level, pair level, word level, or stream level?
- 90% under what spacing, signal condition, speed, anchor, and confirmation
  support?
- 90% with what kind of errors: misses, substitutions, transpositions, delayed
  responses, or self-corrections?

The result is symbol collapse. A learner, a tool, or a community guideline may
treat "90%" as a stable measurement when it is actually a mixture of several
distinct auditory burdens. Accuracy on a four-symbol isolated recognition task
is not equivalent to accuracy on a ten-symbol set. Accuracy on `K`, `M`, `R`,
and `U` as single symbols is not equivalent to accuracy on `KR`, `MU`, `RK`,
`MUM`, or `RU` under time pressure.

This matters because Morse learning is not only a question of identifying
individual characters. It is the formation of direct sound-to-meaning pathways
under increasing auditory load. A learner may appear competent under one unit
of measurement and then fail under another, not because they have regressed, but
because the task has changed.

Copy's recognition data shows this clearly. A learner may feel they have spent
"a lot of time" in a claimed range, while the actual recorded contact time is
small. In the current recognition data, 68 saved sessions across the claimed set
`K M R U` amount to about 74.6 minutes of wall-clock session time. Within that,
Gear 1 pair recognition accounts for only about 12.6 minutes. Yet the background
data still shows meaningful improvement: weak symbols stabilize, misses
disappear, and the active burden moves from isolated symbol recognition toward
short auditory grouping.

The methodological problem is therefore not whether Koch should be rejected. It
should not. The problem is how to preserve Koch's controlled acquisition insight
without flattening progression into a single accuracy threshold.

## 2 Introduction

Copy is a listening-first Morse environment. Its interface is intentionally
minimal because the screen is not the primary learning surface. The learner's
attention belongs to the audio. The application should move out of the way as
symbol recognition becomes more competent.

This creates a deliberate separation between three things that many Morse
learning tools collapse:

- training
- practice
- metrics

Copy's position is that metrics should not become the exercise. Progression
evidence can be collected in the background, but the learner should not be
forced into a screen-mediated scoring loop. The system can describe what
happened after the listening act without turning the session itself into a
visual or gamified task.

This document develops progression around three linked concepts:

1. Burdens: what creates load.
2. Debt: what remains unresolved.
3. Probes: how uncertainty is reduced.

This framing moves the progression question away from "when should the next
symbol be added?" and toward "which burden should be introduced, serviced, or
sampled next?" A new symbol is one possible burden. It is not the whole
progression model.

The current Symbol Recognition mode is an example of this approach. During a
recognition session, the learner listens and speaks. The system records the
truth schedule, the learner's spoken response as heard by the recognizer, the
editable saved answer, and derived analysis. The learner does not need to watch
the screen during the exercise. The data remains available afterward for
reflection, review, and progression research.

The aim of this document is to describe the current recognition JSON format and
explain why each section exists. This is not yet a proposal for a final
progression model. It is the first paper step: establish what is already being
collected, what each part means, and how the format supports a richer view of
Koch progression than a flat accuracy threshold.

## 3 Training vs Practice

Copy should distinguish training from practice.

Training is constrained acquisition. It deliberately narrows the task so a
particular listening pathway can form. In Symbol Recognition, the learner hears
a known symbol or short unit and makes a direct recognition claim. The system can
record that claim, compare it to the truth, and preserve evidence about misses,
substitutions, self-corrections, and latency. The purpose is not to simulate
real copy. The purpose is to strengthen a particular auditory mapping under
controlled conditions.

Practice is broader application. In Koch Exercises, the learner listens to a
stream and reconciles afterward. The notebook and the listener's own reflective
process remain central. The system can expose the truth and record useful
session evidence, but it should not turn the practice act into a live scoring
task. Practice asks whether the learner can remain with the stream, tolerate
uncertainty, recover from gaps, and make meaning from a changing signal.

Both modes can share the same 20 WPM character-speed baseline, but they should
not be interpreted as the same kind of evidence.

- Symbol Recognition is training evidence: direct, constrained, and suitable for
  detailed symbol-level analysis.
- Koch Exercises are practice evidence: broader, reflective, and closer to the
  listening loop the learner is trying to inhabit.

This distinction matters because a progression model should not collapse
training and practice into one score. A symbol may be stable in Symbol
Recognition while still fragile in stream practice. Conversely, a learner may
handle a practice stream well while a controlled recognition task reveals a
specific recurring substitution. These are not contradictions. They are
different views of the same developing auditory system.

## 4 Current Recognition JSON Format

Recognition records are saved as one JSON file per completed recognition
session. Files currently live under:

```text
<save_directory>/recognition/YYYY/MM/set-<set_id>/session-NN.json
```

For example:

```text
/Users/aapark/.local/share/copy_653/recognition/2026/06/set-20260601T193718Z/session-04.json
```

The current top-level shape is:

```json
{
  "schema_version": "2.1",
  "engine_version": "0.1.0",
  "mode": "recognition",
  "started_at": "2026-06-01T20:31:54.662Z",
  "ended_at": "2026-06-01T20:32:32.039Z",
  "audio": {},
  "claimed_set": [],
  "seed": 0,
  "generation": {},
  "exercises": [],
  "symbols": []
}
```

The following sections describe each part.

## 5 Top-Level Envelope

### 5.1 `schema_version`

Identifies the shape of the saved record. This lets future tooling distinguish
old records from newer records if the format changes.

Current purpose:

- protect analysis code from silent shape drift
- allow migration or backfill logic
- make saved records auditable over time

### 5.2 `engine_version`

Records the Copy engine version that produced the session.

Current purpose:

- connect observed data to the implementation that generated it
- help explain changes in behavior after engine updates
- support later research into whether data from different engine versions should
  be compared directly

### 5.3 `mode`

For Symbol Recognition records, this is:

```json
"mode": "recognition"
```

Current purpose:

- distinguish recognition records from Koch listening, cadence sending, and
  copy-key records
- allow shared loaders to filter by session type

### 5.4 `started_at` and `ended_at`

UTC timestamps for the session.

Current purpose:

- calculate wall-clock session duration
- build practice calendars
- compare perceived effort against actual recorded contact time
- order records for trend analysis

Important methodological note: wall-clock session duration is not the same as
Morse contact time. It includes spacing, silence windows, recognizer waiting,
and session mechanics. This makes it useful as an upper bound, not as a pure
measure of auditory exposure.

### 5.5 `claimed_set`

The learner's claimed symbol range at the time of the session.

Example:

```json
"claimed_set": ["K", "M", "U", "R"]
```

Current purpose:

- define the symbol inventory from which exercises may be generated
- prevent unknown symbols from entering recognition practice
- preserve the learner's navigated state at the time of the session

Methodological note: `claimed_set` is the learner's declared working range. It
is not proof of mastery. It is the bounded vocabulary within which practice is
generated.

### 5.6 `seed`

The random seed used to generate session content.

Current purpose:

- make generated exercises reproducible in principle
- support debugging when a particular sequence exposes a problem
- preserve the exact generation context alongside the record

## 6 `audio`

The `audio` object snapshots the audio parameters used during the session.

Example:

```json
{
  "character_speed_wpm": 20,
  "effective_speed_wpm": 10,
  "tone_frequency_hz": 600,
  "amplitude": 0.4,
  "envelope_ramp_seconds": 0.007,
  "receiver_bed": 2,
  "cadence_variation": 1,
  "sample_rate_hz": 44100
}
```

Current purpose:

- preserve the listening condition under which recognition evidence was formed
- separate symbol acquisition from signal condition
- prevent accuracy from being interpreted without its auditory context

This section matters because "90%" under one audio condition is not equivalent
to "90%" under another. Character speed, effective speed, receiver bed, cadence
variation, and tone all change the burden.

### 6.1 `character_speed_wpm`

The speed of the individual Morse character shapes.

Current purpose:

- preserve whether the learner is hearing symbols at target auditory speed
- distinguish shape recognition from slow visual-style decoding

### 6.2 `effective_speed_wpm`

The effective speed after spacing is included.

Current purpose:

- capture thinking time between symbols or groups
- distinguish fast character speed with generous spacing from truly dense copy

### 6.3 `receiver_bed`

The level of background receiver texture/noise.

Current purpose:

- represent signal complexity
- support progression that increases realism without increasing symbol set size

### 6.4 `cadence_variation`

The amount of timing variation applied to the signal.

Current purpose:

- represent operator-like rhythmic variation
- distinguish clean mechanical recognition from more realistic listening

## 7 `generation`

The `generation` object describes how the session was generated and how it fits
into the recognition progression system.

Example:

```json
{
  "profile_version": "recognition-progression-v1",
  "claimed_set_key": "K M R U",
  "exercise_count": 5,
  "gear": 1,
  "bands": [
    {"index": 1, "gear": 1},
    {"index": 2, "gear": 1},
    {"index": 3, "gear": 1},
    {"index": 4, "gear": 1},
    {"index": 5, "gear": 1}
  ],
  "set_id": "20260601T193718Z",
  "set_session": 4,
  "recognition": {
    "say_before": false,
    "morse_count": 1,
    "recognition_time_ms": 1500,
    "say_after": true
  },
  "run_index": 68
}
```

### 7.1 `profile_version`

Identifies the recognition generation profile.

Current purpose:

- distinguish this progression format from future formats
- make it possible to interpret historical records correctly

### 7.2 `claimed_set_key`

A normalized string form of the claimed set.

Example:

```json
"claimed_set_key": "K M R U"
```

Current purpose:

- group records by equivalent claimed range
- avoid treating different display order as different practice domains
- aggregate evidence for the same controlled symbol inventory

### 7.3 `exercise_count`

The number of exercises in the session.

Current purpose:

- preserve the session structure
- validate saved answers and voice capture against expected exercise count

### 7.4 `gear`

The current recognition gear for the session.

Current purpose:

- describe the unit of recognition being trained
- separate isolated-symbol competence from grouped recognition

Current gear interpretation:

- Gear 0: single-symbol recognition
- Gear 1: two-symbol pair recognition
- Gear 2: multiple two-symbol units
- Gear 3 and above: short word-like units with greater auditory burden

Methodological note: gear is not a learner-facing grade. It is a backend
description of task shape.

### 7.5 `bands`

Per-exercise-slot gear metadata.

Example:

```json
[
  {"index": 1, "gear": 1},
  {"index": 2, "gear": 1},
  {"index": 3, "gear": 1},
  {"index": 4, "gear": 1},
  {"index": 5, "gear": 1}
]
```

Current purpose:

- preserve the gear used for each exercise slot
- support older or future per-band progression analysis
- make the record explicit even when all slots use the same gear

Current implementation note: recognition currently resolves one set-level gear
and applies it to all exercise slots.

### 7.6 `set_id`

Identifies the 8-session recognition set.

Current purpose:

- group sessions into a controlled progression block
- hold gear constant across a set
- allow set-level evidence to be evaluated only after enough sessions exist

### 7.7 `set_session`

The session number within the current 8-session set.

Current purpose:

- preserve position within the set
- prevent gear changes halfway through a set
- distinguish partial evidence from completed set evidence

### 7.8 `recognition`

The recognition-mode settings used for this session.

Fields:

- `say_before`: whether the spoken anchor is played before Morse
- `morse_count`: how many times the Morse unit is played
- `recognition_time_ms`: recognition window after playback
- `say_after`: whether the spoken anchor is played after Morse

Current purpose:

- preserve anchor and repetition support
- distinguish aided recognition from unaided recognition
- place accuracy in its training context

### 7.9 `run_index`

Sequential recognition run count for the claimed set.

Current purpose:

- show accumulated practice count
- support settings-table display and historical inspection

Methodological note: run count is not the same as practice depth. Many runs can
still represent a small amount of actual auditory contact time.

## 8 `symbols`

The `symbols` array is the played truth timeline.

Example entry:

```json
{
  "symbol": "M",
  "t_on": 0.0055,
  "t_off": 0.8241,
  "exercise_index": 1,
  "word_index": 1,
  "word": "MU"
}
```

Current purpose:

- record exactly what was played
- preserve timing for each symbol
- allow voice responses to be reconstructed against the audio timeline
- support latency and timing analysis

### 8.1 `symbol`

The truth symbol played.

Current purpose:

- count exposures
- build per-symbol evidence
- identify confusion targets

### 8.2 `t_on` and `t_off`

Session-relative onset and offset times for the symbol.

Current purpose:

- align spoken responses to the symbol timeline
- calculate response latency
- distinguish fluent recognition from delayed recognition

### 8.3 `exercise_index`

The exercise containing the symbol.

Current purpose:

- group the flat timeline back into exercises
- connect truth schedule to saved answer and voice capture

### 8.4 `word_index` and `word`

The generated unit containing the symbol.

Current purpose:

- represent grouped tasks such as pairs and short words
- distinguish symbol recognition from unit-level recognition
- support future analysis of pair, word, and sequence burdens

## 9 `exercises`

The `exercises` array stores one object per recognition exercise.

Example shape:

```json
{
  "index": 1,
  "target": "MU",
  "burden_band": 1,
  "gear": 1,
  "recognition_kind": "pairs",
  "answer": "MU",
  "voice_capture": [],
  "analysis": {},
  "timing_analysis": {}
}
```

Current purpose:

- hold the generated target
- hold the learner's saved answer
- hold raw recognizer evidence
- hold derived progression and timing analysis

### 9.1 `index`

The 1-based exercise number in the session.

Current purpose:

- preserve exercise order
- connect UI rows, truth timeline, and voice capture

### 9.2 `target`

The generated target for the exercise.

Examples:

```json
"K M U R"
"MU"
"RK"
```

Current purpose:

- expose the truth after the session
- define what the learner was responding to
- distinguish singles from grouped units

### 9.3 `burden_band`

The exercise slot used for band-style analysis.

Current purpose:

- preserve compatibility with per-slot progression concepts
- allow the system to ask whether early, middle, or late exercises carry
  different burden

Current implementation note: in recognition, this usually follows the exercise
index.

### 9.4 `gear`

The gear used for this exercise.

Current purpose:

- make each exercise self-describing
- allow analysis to interpret `target` in the correct task context

### 9.5 `recognition_kind`

Human-readable task kind derived from gear.

Examples:

```json
"single-symbols"
"pairs"
"words"
```

Current purpose:

- make records easier to inspect
- support settings and review UI

### 9.6 `answer`

The learner's saved answer for the exercise.

Current purpose:

- capture what the learner committed after the session
- allow review-time correction of recognizer output
- support answer-aligned progression evidence

Methodological note: `answer` is currently the source for the persisted
`analysis` block. This means progression is based on the saved answer rather
than solely on the raw recognizer transcript.

### 9.7 `voice_capture`

The raw recognizer finals captured during the exercise.

Example entry:

```json
{
  "t": 4.2041,
  "text": "mike uniform",
  "symbols": ["M", "U"],
  "first_partial_t": 3.8122,
  "last_partial_t": 4.0018,
  "symbol_events": [
    {"index": 1, "symbol": "M", "t": 3.8122, "source": "partial"},
    {"index": 2, "symbol": "U", "t": 4.0018, "source": "partial"}
  ]
}
```

Current purpose:

- preserve what the speech recognizer heard
- preserve timing of spoken recognition
- support self-correction and latency analysis
- distinguish recognizer behavior from learner-saved answer

Methodological note: this is one of the most important parts of the format.
It allows Copy to keep an honest record of in-the-moment spoken evidence without
forcing that evidence to become the only progression signal.

## 10 `analysis`

The `analysis` object is the answer-aligned derived result for an exercise.

Example:

```json
{
  "version": "recognition-analysis-v1",
  "method": "answer-alignment",
  "saved": true,
  "has_evidence": true,
  "committed_answer": "MU",
  "counts": {
    "correct": 2,
    "substitution": 0,
    "caught_correct": 0,
    "caught_substitution": 0,
    "miss": 0
  },
  "combined_fraction": 1.0,
  "recognition_state": "exact",
  "band_state": "exact",
  "burden_band": 1,
  "gear": 1,
  "committed_confusions": [],
  "caught_confusions": [],
  "ambiguous_lag": false,
  "slots": []
}
```

Current purpose:

- provide the current progression evidence
- align saved answer against target
- generate per-exercise state
- support settings summaries and confusion reports

### 10.1 `method`

Current value:

```json
"answer-alignment"
```

Current purpose:

- state that the analysis is based on saved answer alignment
- distinguish it from timing/onset-window analysis

### 10.2 `has_evidence`

Whether the exercise produced usable answer evidence.

Current purpose:

- avoid treating silence as either success or failure in aggregate confusion
  analysis
- separate "nothing heard/saved" from an incorrect committed answer

### 10.3 `committed_answer`

The normalized answer used for analysis.

Current purpose:

- preserve the exact string being scored by the derived layer
- make analysis auditable

### 10.4 `counts`

Outcome counts for the exercise.

Fields:

- `correct`
- `substitution`
- `caught_correct`
- `caught_substitution`
- `miss`

Current purpose:

- distinguish different error shapes
- avoid collapsing misses, wrong symbols, and self-corrections into a single
  failure bucket

Current implementation note: because `analysis` is answer-aligned, caught
self-corrections are usually represented in `timing_analysis`, not in
`analysis`.

### 10.5 `combined_fraction`

The per-exercise fraction used by the current progression layer.

Current purpose:

- summarize exercise-level result
- feed recognition-state and set-level evidence

Methodological warning: this is useful but incomplete. It should not be read as
"the learner knows the symbol." It is a compact result for a specific exercise
under a specific generation and audio context.

### 10.6 `recognition_state` and `band_state`

Categorical states derived from `combined_fraction`.

Current states include:

- `silent`
- `low`
- `building`
- `steady`
- `strong`
- `exact`

Current purpose:

- provide coarse evidence categories
- support progression without presenting raw scores as learner-facing grades

### 10.7 `committed_confusions`

Pairs of target and committed wrong symbol.

Example:

```json
[["U", "R"]]
```

Current purpose:

- identify recurring substitutions
- show that "wrong" is not generic
- support symbol-specific improvement analysis

### 10.8 `caught_confusions`

Pairs of target and superseded wrong symbol.

Current purpose:

- preserve self-correction evidence
- distinguish "nearly read as R, corrected to U" from "committed R for U"

Current implementation note: caught confusions are primarily visible through
`timing_analysis`, because `analysis` is currently answer-aligned.

### 10.9 `ambiguous_lag`

Boolean flag for cases where timing may not cleanly distinguish a
self-correction from falling behind.

Current purpose:

- mark analysis that should be interpreted cautiously
- prevent overconfidence in per-slot classification

### 10.10 `slots`

Per-symbol analysis slots.

Example:

```json
{
  "index": 1,
  "truth": "M",
  "tokens": ["M"],
  "committed": "M",
  "superseded": [],
  "outcome": "correct"
}
```

Current purpose:

- preserve symbol-level evidence inside an exercise
- support per-symbol rates, misses, and substitutions
- prevent session-level accuracy from hiding symbol-specific weakness

## 11 `timing_analysis`

The `timing_analysis` object is the onset-window reconstruction of the spoken
recognition attempt.

Current purpose:

- reconstruct what happened in time
- align recognizer events to the played symbol schedule
- preserve self-corrections and response latency
- provide diagnostic evidence distinct from saved-answer progression

The shape is similar to `analysis`, but its `method` is:

```json
"onset-window"
```

This method uses `symbols` and `voice_capture` to assign spoken tokens to played
symbol windows. Within a window, the final token is treated as committed and
earlier tokens are treated as superseded.

Methodological importance:

- `analysis` answers: what did the learner save?
- `timing_analysis` answers: what did the recognizer hear during the listening
  act, and when?

Both are useful. Neither should be silently collapsed into the other.

## 12 Current Progression Use

Recognition progression currently operates at set level.

Current behavior:

- a recognition set contains 8 sessions
- each session contains 5 exercises
- gear is held constant across the set
- after a completed set, evidence is aggregated
- one strong completed set can move gear upward
- two low completed sets are required to move gear downward

This is intentionally more stable than moving after a single good session. It
also avoids changing the task shape mid-set.

Current limitation:

The system records symbol-level evidence, but progression is not yet truly
symbol-level. The current gear changes the exercise unit globally. It does not
yet maintain an independent evidence state for each symbol, confusion pair, or
unit shape.

At present, a completed set can move the whole recognition task from one gear to
another. That is useful because it prevents rapid oscillation and gives the
learner repeated contact with the same task shape. But it also means a single
progression decision is being made over a mixed field of evidence. Within the
same set, one symbol may be stable, another may be fragile, and a third may only
be fragile when it appears beside a particular neighbor. The current progression
engine records those facts but does not yet act on them directly.

The data can already support statements such as:

- `M` is stable
- `R` is fragile
- `U -> R` is a recurring confusion
- pair-level `KR` is a different burden from isolated `K` and isolated `R`

Those statements are different from a session score. They describe different
auditory claims:

- `M` is stable means repeated exposures to `M` are being recognized correctly
  across the current claimed range and task shape.
- `R` is fragile means `R` has enough misses, substitutions, hesitation, or
  instability that it should not be treated as equally acquired just because the
  whole session averaged well.
- `U -> R` is a recurring confusion means the learner is not merely "wrong" on
  some attempts; the sound shape for `U` is repeatedly being pulled toward the
  sound/meaning identity of `R`.
- Pair-level `KR` is a different burden from isolated `K` and isolated `R`
  means the learner may recognize both symbols as individual shapes but still
  struggle when they must preserve order, grouping, and short-term auditory
  memory.

This is the central symbol-collapse problem. A global accuracy value can hide
which symbol is doing the work, which symbol is being carried by the others, and
which errors are structurally meaningful. A learner might show 90% across a
session while one symbol remains unstable. Conversely, a learner might show a
drop when moving from singles to pairs even though the underlying single-symbol
recognition has improved. The lower score is not regression; it is evidence
that the task moved from identification to grouped auditory retention.

The same principle applies when a new symbol is added to the claimed set. Old
symbols do not drop out of the system. They remain in the generation pool, which
means the record can show how established symbols behave when the claimed range
changes. This is important because adding a symbol does not only test the new
symbol. It perturbs the whole listening field.

A newly expanded claimed set should be expected to produce some early cognitive
load. Symbols that were previously strong may become less stable for a few
sessions. A familiar symbol may begin to attract or repel the new symbol.
Previously rare confusions may appear because the learner is rebuilding the
rhythm of the set, not because the old symbol has been lost. This early
instability is adaptation evidence.

For example, after adding a new symbol, the useful questions are not only:

- does the learner recognize the new symbol?
- is the total session percentage still high?

The more useful questions are:

- which older symbols remain stable in the expanded range?
- which older symbols become fragile under the new load?
- which new confusion pairs appear?
- do those confusions persist, or do they settle as the rhythm of the set forms?
- does the learner recover old stability after repeated exposure to the expanded
  set?

This is one of the reasons the claimed-set key matters. Progression evidence
belongs to a particular working range. `K M R U` evidence is not simply replaced
when a fifth symbol is added; it becomes the prior context against which the new
claimed range can be understood. A layered progression model should therefore
read early turbulence after expansion as part of acquisition, not as immediate
failure.

A more complete progression model would treat evidence as layered:

- per-symbol stability: how each symbol behaves across repeated exposures
- per-confusion evidence: which substitutions recur and whether they are
  committed or self-corrected
- per-unit burden: whether the learner can carry symbols through pairs, short
  words, and longer grouped forms
- per-condition evidence: whether recognition holds under different spacing,
  receiver bed, cadence variation, and anchor support
- per-time evidence: whether stability persists across sessions rather than
  appearing as a single local success

Under that model, "ready to progress" would not mean "the latest session was
90%." It would mean something closer to:

> The current claimed range is stable enough at the present unit size and
> listening condition that the next burden should be introduced deliberately.

That next burden may not always be a new symbol. It might be a pair-level task,
a word-like unit, a reduction in anchor support, a tighter recognition window,
or a more realistic signal condition. The important methodological shift is
that progression becomes an interpretation of structured evidence, not a direct
conversion from one aggregate accuracy number into an unlock.

## 13 Progression as Burden Selection

The progression question should not be framed only as:

> When should the next symbol be added?

That framing treats symbol inventory as the main curriculum axis. Symbol
inventory matters, but it is only one part of cognitive load. A symbol is learned
inside a broader auditory environment: unit length, spacing, signal condition,
rhythm variation, anchor support, and the learner's ability to keep meaning
forming while the stream continues.

A better progression question is:

> Which burden should be introduced next?

Possible next burdens include:

- a new symbol
- pair recognition
- longer units
- reduced spoken-anchor support
- shorter recognition windows
- increased receiver bed
- increased cadence variation
- tighter effective spacing
- transfer from Symbol Recognition into Koch Exercise practice

This reframes progression as burden selection. The app is not trying to unlock a
linear character list. It is trying to identify the next useful stressor for a
developing auditory system.

Under this model, each burden axis asks a different question:

| Burden axis | Question |
| --- | --- |
| Symbol inventory | Can the learner tolerate a larger known set? |
| Unit length | Can the learner retain sequences, not just identify shapes? |
| Confusion pressure | Which sound shapes are still attracting one another? |
| Signal condition | Does recognition survive receiver bed and degraded audio? |
| Rhythm condition | Does recognition survive cadence variation? |
| Spacing/time | Does recognition survive less recovery time? |
| Anchor support | Does recognition survive without spoken confirmation? |
| Practice transfer | Does training stability survive in stream practice? |

This also clarifies the role of a percentage threshold. A number such as 90% is
not meaningless, but it is incomplete. It is only interpretable when attached to
a burden axis and condition:

- 90% on isolated symbols in a four-symbol claimed set
- 90% on pairs in the same set
- 90% after a newly added symbol perturbs the set
- 90% with receiver bed increased
- 90% with anchors removed

These are different claims. They should not be collapsed.

The next burden should be selected by the evidence profile. For example:

- If singles are stable but pairs are unstable, the next burden is probably unit
  length, not a new symbol.
- If pairs are stable but recognition is overfit to clean audio, the next burden
  may be receiver bed or cadence variation.
- If a specific confusion pair persists, the next burden may be targeted
  contrast exposure rather than broader progression.
- If the claimed range is stable across current unit length and condition, the
  next burden may be a new symbol.

This keeps Koch's controlled acquisition insight while avoiding the watered-down
version in which every progression decision becomes "add the next character."

## 14 Burden Debt

Burden selection becomes more useful if unresolved instability is treated as
debt.

Not symbol debt. Burden debt.

Burden debt is the unresolved instability exposed by a specific burden axis. It
does not mean the learner has failed. It means the current evidence shows a
burden that still needs service before the next larger burden is likely to be
useful.

The working model is:

```text
                Burdens
                   |
                   v
             Debt Profile
                   |
        +----------+----------+
        |                     |
        v                     v
   Unknown Debt           Known Debt
        |                     |
        v                     v
      Probes          Exercise Tailoring
        |                     |
        +----------+----------+
                   |
                   v
            Updated Evidence
                   |
                   v
             Debt Revision
                   |
                   v
              Soft Nudge
```

Examples:

- Symbols stable, pairs unstable: unit-length debt.
- Pairs stable, cadence variation unstable: rhythm debt.
- Singles stable, receiver bed unstable: signal debt.
- Clean recognition stable, anchor-free recognition unstable: anchor debt.
- Symbol Recognition stable, Koch Exercise practice unstable: transfer debt.

This lets progression be described as a profile rather than a ladder:

```text
Progression State
  Symbol Inventory Burden: low debt
  Unit-Length Burden: moderate debt
  Confusion Burden: moderate debt
  Signal Burden: low debt
  Rhythm Burden: unknown debt
  Anchor Burden: low debt
  Practice Transfer Burden: unknown debt
```

The next burden is chosen by the debt profile. A learner whose symbols are
stable but whose pairs are unstable does not need more symbols. They need to
service unit-length debt. A learner whose pairs are stable but whose cadence
variation is unstable does not need a larger claimed set. They need to service
rhythm debt.

Debt should include confidence as well as severity. Unknown debt is not low
debt. It means the system does not yet have enough evidence.

For example:

```text
R Symbol Burden
  Debt: moderate
  Confidence: high
  Evidence: repeated misses and R/K substitutions across many exposures

M Symbol Burden
  Debt: low
  Confidence: high
  Evidence: stable across singles and pairs

Rhythm Burden
  Debt: unknown
  Confidence: low
  Evidence: not enough cadence-varied recognition data
```

This prevents the system from mistaking absence of evidence for evidence of
stability. A burden that has not been tested should not be treated as mastered.
It should be available as a small probe.

The app can use burden debt in the background to tailor exercises:

- If symbol debt is high, keep the task narrow and strengthen isolated or
  contrast recognition.
- If confusion debt is high, bias exercises toward the unstable contrast pairs.
- If unit-length debt is moderate, keep the claimed set stable and emphasize
  pairs or short units.
- If signal debt is high, keep unit length stable and increase receiver bed
  gradually.
- If rhythm debt is high, keep the symbol set stable and introduce cadence
  variation.
- If debt is unknown, introduce small probes rather than full progression.

The learner does not need to see this whole profile during listening. The
learner-facing signpost can remain soft and simple:

> Evidence suggests you are ready to consider the next symbol.

That nudge is the visible endpoint of a hidden debt profile. It should appear
only when the current evidence suggests that symbol debt is low, major confusion
debt is low or improving, unit-length debt is not severe, and recent instability
is not merely turbulence from a newly introduced burden.

The nudge remains non-binding. The learner is still the authority. The app uses
burden debt to shape practice and training quietly, not to enforce a curriculum.

## 15 Recognition Practice Needs

Recognition Practice Needs is the current learner-facing view of the burden debt
profile for Symbol Recognition. It is not a scorecard and it is not a direct
progression gate. It is a compact explanation of what the saved Recognition
evidence currently says about the learner's auditory burden.

The table has three columns:

| Column | Meaning |
| --- | --- |
| Area | The burden axis being described. |
| Practice need | The unresolved debt on that axis: low, moderate, high, or unknown. |
| Confidence | How much evidence supports that interpretation. |

The important distinction is that "unknown" is a real state. It does not mean
the learner is weak, and it does not mean the learner is stable. It means Copy
does not yet have the right kind of controlled evidence for that burden. Unknown
practice needs should lead to small probes, not to punishment or blocked
progression.

Current Recognition Practice Needs align to the method as follows:

| Practice need area | Method axis | Current interpretation |
| --- | --- | --- |
| Symbols | Symbol inventory | Per-symbol recognition stability within the current claimed set. This uses exposures, correct recognitions, misses, substitutions, recent trend, and evidence since introduction. |
| Unit length | Unit length | Whether the learner is carrying grouped units such as pairs or short word-like units, not only identifying isolated symbols. |
| Confusions | Confusion pressure | Whether specific sound shapes are attracting one another through committed substitutions or caught self-corrections. |
| Listening conditions | Signal condition | Whether recognition holds when the receiver bed or related listening condition changes under controlled evidence. |
| Rhythm | Rhythm condition | Whether recognition survives cadence variation. This remains unknown until cadence-varied Recognition probes exist. |
| Anchor | Anchor support | Whether recognition survives reduced or removed spoken confirmation. This remains unknown until anchor contrast probes exist. |
| Practice transfer | Practice transfer | Whether Symbol Recognition stability carries into Koch Exercise stream practice. This remains unknown until the two modes are linked analytically. |

The Symbols detail is intentionally richer than a single percentage. It can show
each symbol's lifetime and recent evidence, trend, misses, substitutions, and
status. This is where the table most directly resists symbol collapse: one
overall Recognition percentage may look acceptable while a particular symbol is
still fragile, undersampled, or only recently recovering.

The Unit length row is similarly separate from Symbols. A learner can recognize
`K`, `M`, `R`, and `U` as isolated symbols while still struggling with `KR`,
`MU`, or `RU` as short auditory units. That is not regression. It means the
burden moved from symbol identification to grouped retention.

The Confusions row treats wrong answers as structured evidence. A repeated
`U -> R` substitution is not the same as a random miss, and a caught
self-correction is not the same as a committed wrong answer. Both matter because
they reveal how sound shapes are settling, competing, or being repaired during
the listening act.

Listening conditions, Rhythm, Anchor, and Practice transfer should stay
conservative. They should not be marked as low debt simply because normal
Recognition sessions do not test them. They become knowable only through
controlled probes or comparable contrast evidence where one burden changes and
the rest of the environment remains stable.

The Estimated Time in Session section is related but separate. It is a
learner-facing estimate based on saved Recognition time and current performance.
It helps the learner understand scale and effort, but it should not replace the
Practice Needs table. Time can say roughly how much more contact may be needed;
Practice Needs explains which burden that contact should probably service.

## 16 Probes

Burden debt creates a second useful concept: probes.

A probe is a tiny, low-cost burden experiment designed to answer:

> Do we know enough about this burden yet?

Probes are not tests. They are not gotchas. They are not pass/fail gates. A
probe is a small sample of evidence that helps the system distinguish low debt
from unknown debt, or suspected debt from confirmed debt.

The central rule is that a probe should change one burden axis at a time. If the
system changes symbol set, unit length, receiver bed, and cadence variation all
at once, the resulting instability cannot be interpreted cleanly. A useful probe
keeps the rest of the environment stable and samples one question.

Examples:

```text
Cadence Probe
  Purpose: sample rhythm debt
  Shape: 2 exercises
  Change: high cadence variation
  Constraint: keep claimed set, unit length, signal, and anchor support stable

Anchor Probe
  Purpose: sample anchor debt
  Shape: 2 exercises
  Change: no spoken confirmation
  Constraint: keep claimed set, unit length, signal, and cadence stable

Signal Probe
  Purpose: sample signal debt
  Shape: 2 exercises
  Change: receiver bed +1
  Constraint: keep claimed set, unit length, cadence, and anchor support stable
```

A probe result should be interpreted as evidence, not judgment:

```text
Cadence Probe Result
  Burden: rhythm
  Result: debt detected
  Confidence: low
  Evidence: recognition dropped under cadence variation

Signal Probe Result
  Burden: signal
  Result: no debt detected
  Confidence: low
  Evidence: recognition remained stable under receiver bed +1

Anchor Probe Result
  Burden: anchor
  Result: inconclusive
  Confidence: low
  Evidence: too few usable voiced responses
```

This gives Copy a useful hierarchy:

- burden: an axis of cognitive or audio load
- debt: unresolved instability on that axis
- probe: a small experiment to measure unknown or suspected debt
- exercise tailoring: repeated practice to service known debt
- soft nudge: the quiet learner-facing signpost produced after the debt profile
  is sufficiently settled

Probes should remain structurally modest. They should be short enough that they
do not feel like a mode change, a challenge, or a hidden exam. Their purpose is
to improve the background model so the app can choose better future exercises.

## 17 Current Data as Progression Evidence

The current recognition dataset is small, but it already demonstrates why
background evidence is useful. The local recognition records contain:

- 68 recognition sessions
- 9 recognition sets
- 8 completed recognition sets
- 74.6 minutes of wall-clock recognition-session time
- 1160 played symbol exposures
- one claimed set: `K M R U`

This is not enough data to claim a general progression law. It is enough to show
that the record format captures change over time.

Set-level progression from the current data:

| Set                | Gear | Sessions | Minutes | Symbols | Avg fraction |      K |      M |     R |      U |
| ------------------ | ----:| --------:| -------:| -------:| ------------:| ------:| ------:| -----:| ------:|
| `20260530T105837Z` |    0 |        8 |     9.9 |     160 |        76.4% |  70.6% | 100.0% | 57.1% |  82.2% |
| `20260530T113645Z` |    0 |        8 |    10.1 |     160 |        68.1% |  68.0% | 100.0% | 54.3% |  60.0% |
| `20260530T115116Z` |    0 |        8 |    10.0 |     160 |        75.0% |  81.1% | 100.0% | 55.0% |  70.6% |
| `20260530T122131Z` |    0 |        8 |    10.5 |     160 |        96.9% | 100.0% |  97.9% | 96.7% |  94.3% |
| `20260530T125419Z` |    1 |        8 |     4.9 |      80 |        65.0% |  42.9% |  95.0% | 61.9% |  61.1% |
| `20260531T174129Z` |    0 |        8 |    10.7 |     160 |        91.9% |  90.9% | 100.0% | 94.1% |  82.2% |
| `20260601T173559Z` |    0 |        8 |    10.7 |     160 |        98.8% | 100.0% | 100.0% | 98.0% |  97.3% |
| `20260601T180732Z` |    1 |        8 |     5.2 |      80 |        88.8% |  88.0% | 100.0% | 88.0% |  87.5% |
| `20260601T193718Z` |    1 |        4 |     2.5 |      40 |        95.0% | 100.0% |  80.0% | 88.9% | 100.0% |

The pattern is visible:

- `M` is stable early and remains strong.
- `R` is fragile early, then stabilizes at Gear 0.
- `K` and `U` also stabilize over repeated Gear 0 exposure.
- The first move into Gear 1 causes a sharp drop. This is not regression; the
  burden changed from isolated-symbol identification to pair recognition.
- Later Gear 1 evidence improves, showing that the learner is adapting to the
  new unit burden.

The dominant committed confusions also show that errors are structured, not
generic:

| Confusion | Count |
| --- | ---: |
| `U -> R` | 23 |
| `K -> R` | 16 |
| `R -> K` | 12 |
| `R -> U` | 8 |
| `K -> M` | 3 |
| `K -> U` | 2 |

Caught self-corrections show a related but distinct stream:

| Caught confusion | Count |
| --- | ---: |
| `U -> R` | 11 |
| `U -> K` | 7 |
| `M -> R` | 7 |
| `M -> U` | 6 |
| `R -> K` | 4 |
| `K -> U` | 4 |

This supports the burden-selection view. The data does not merely say "the
learner scored X." It says which symbols were stable, which symbols were
fragile, which confusions recurred, and how performance changed when the burden
shifted from singles to pairs.

This kind of summary can be produced with analysis tooling such as pandas or
NumPy once a larger dataset exists. The important point is not the specific
tooling. The important point is that the JSON record already contains enough
structure to support longitudinal progression analysis.

## 18 Why This Structure Matters

The current JSON format already avoids the most damaging form of symbol
collapse. It does not only store a session score. It stores:

- claimed symbol range
- audio condition
- generation profile
- gear and unit shape
- exact played timeline
- saved learner answer
- raw voice capture
- answer-aligned analysis
- onset-window timing analysis
- per-symbol slots
- committed substitutions
- caught self-corrections

This makes it possible to say something more precise than "90% accurate."

For example:

> In the claimed range `K M R U`, isolated symbol recognition has stabilized,
> while the current burden has moved to short grouped recognition. The remaining
> evidence is not generic inaccuracy; it is concentrated around specific
> substitutions and the transition from singles to pairs.

That is closer to controlled auditory acquisition than a flat progression
threshold.
