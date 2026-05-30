# Copy — Philosophy and Methodology

Version 0.1.0

## 1 Overview

Copy is a listening environment for CW.

It is not:

- a teacher
- a scoring system
- a progression tracker
- a community

Modern CW learning tools often optimise for interaction with the software rather than interaction with the real-world skill. Copy reverses that relationship.

The project supports the development of:

- auditory immersion
- signal recognition
- uncertainty tolerance
- confidence formation
- reflective listening
- realistic copy

The intended learner is one who wants to develop the actual skill rather than proficiency at interacting with training software.

---

## 2 The Skill Being Trained

Receiving CW is fundamentally an auditory and cognitive discipline.

It is not primarily:

- a typing exercise
- a reaction-time test
- a visual recognition problem

CW listening involves:

- partial copy
- environmental noise
- imperfect signals
- fading
- variable operator rhythm ("fist")
- uncertainty
- delayed understanding
- contextual inference
- confidence weighting

Experienced operators do not consciously decode individual dits and dahs character-by-character.

They develop:

- auditory shape recognition
- rhythm familiarity
- phrase anticipation
- pattern grouping
- contextual prediction

The pedagogical move Copy makes is therefore to train:

direct sound → meaning pathways

rather than:

sound → visual symbol → meaning pathways.

The foundational premise: humans learn auditory systems most effectively when immersion, uncertainty, reflection, and realism are preserved. Copy is the structure that preserves them.

---

## 3 Named Design Contracts

The following contracts are load-bearing. They are stated once, here, and every other decision in Copy is downstream of them.

### 3.1 The screen is not the protagonist

The learner's attention belongs to the audio. The screen exists to deliver and to expose; it does not narrate, score, or interrupt. The paper notebook is part of the interface. The software's success is measured by how little of the listening session passes through it.

### 3.2 The meaning anchor comes from the radio vocabulary, not the literacy vocabulary

A new symbol is introduced by pairing its CW pattern with a spoken anchor. That anchor must come from the working vocabulary of radio communication, not from the letter names of written language.

In practice, this means NATO phonetic — "Kilo" rather than "kay", "Mike" rather than "em", "Whiskey" rather than "double-you". This choice is not aesthetic. Radio vocabularies were built to be unambiguous over voice under degraded conditions; they are the right anchors for an auditory skill that will be exercised in similar conditions.

The principle generalises beyond letters. Anchors for callsigns, prosigns, or whole transmissions ("CQ CQ CQ") follow the same rule: the spoken form is the radio form.

### 3.3 Verification is deferred, and the form of verification matches the form of the claim

The system does not interrupt listening to ask whether the learner heard correctly. Verification, when it happens at all, happens after the listen.

Different exercises produce different kinds of claim, and the verification mechanism must match:

- A reconstruction claim — partial copy in personal shorthand, captured in the paper notebook — is reflected against the truth, not graded by it.
- An active-acknowledgement claim — a keypress or radio gesture (e.g. keying "R") made in real time — is reconciled against the truth on a timeline.

Verification is never softer than the claim it answers, and never harder. Where both kinds of claim are made within one session, both are answered in their respective forms.

### 3.4 The honesty contract

When Copy reports truth, it reports it plainly. If the learner marked seven and the stream contained twelve, the review shows seven and twelve. No softening, no rounding, no encouragement copy, no streak preservation, no manufactured warmth. The system does not flatter the learner because flattery breaks the contract that makes the verification useful in the first place.

### 3.5 Symbol Simplicity vs Signal Complexity

Two axes of difficulty exist independently:

- **Symbol complexity** — the number of symbols the learner has claimed competence in.
- **Signal complexity** — the realism and imperfection of the listening environment (fading, static, fist variation, tone variation, weak-signal emergence, imperfect rhythm).

Many training systems grow both at once. Copy holds the symbol set small (only known symbols appear in any stream) and grows signal complexity as the working axis. This reflects how listening competence is actually developed: the vocabulary stays bounded; the conditions get harder.

### 3.6 The mentor is structurally absent and that absence is acknowledged

Copy does not simulate a teacher. It does not generate hints, encouragement, corrections, or pedagogical commentary. The mentor's chair is empty, and Copy does not pretend to fill it.

This is a real cost — a mentor would be useful. But a simulated mentor is worse than no mentor: it teaches the learner to defer to the simulation rather than to develop their own listening. Copy chooses honest absence over false presence.

### 3.7 The learner navigates; the app may signpost but never gates

All exercises are available at all times. There is no curriculum, no unlock structure, no "complete X before Y." Copy may suggest sensible next steps; it does not enforce them. The learner is the authority on where they are.

### 3.8 The notebook is part of the system, not an input device

The paper notebook is treated as an active cognitive instrument within the listening process — not as legacy workflow, not as scaffolding to be replaced by digital input later. Copy never asks the notebook to align with software state, produce machine-readable entries, or follow standard notation. The notebook is the learner's; what appears in it is the learner's evolving listening cognition.

---

## 4 The Three Cognitive Modes

Copy comprises three modes. Introduction is exposure to a new symbol. The two listening modes — Detection and Full Copy — share a single canonical loop:

listen → notebook → post-exercise review.

They differ only in what the learner is asked to listen for.

### 4.1 Introduction — delivery only

The learner is introduced to a symbol by a paired playback: the spoken anchor (per 3.2) followed by the CW pattern. The session is delivery-only. The learner makes no claim, performs no marking, and receives no verification. Introduction is exposure, not exercise. The learner moves on when they choose to.

### 4.2 Detection — recognition under stream

The learner listens to a stream of known symbols and tracks occurrences of a chosen target (a single symbol, or a small set within the known alphabet). The canonical capture is the paper notebook: a tally, a list, a personal mark for each occurrence the learner believes they heard. Post-session, Copy displays what was sent and the learner reflects against their notebook.

A learner with paddle or key hardware may optionally send an active acknowledgement in real time — keying "R" when the target is heard, for example, or pressing a single key. When this layer is enabled, Copy records the input alongside the truth and produces a timeline reconciliation in addition to the notebook reflection.

The active-acknowledgement layer does not turn Detection into a transmission trainer. Send and receive are different domains; Copy is a receive-training tool. The acknowledgement gesture is permitted because it is operationally authentic — operators do acknowledge — but its presence or absence is the learner's choice, not the system's requirement.

### 4.3 Full Copy — listening for everything

The learner listens to a stream of known symbols and writes what they hear in their notebook, in their own evolving shorthand. Post-session, Copy displays what was sent. The learner reflects against their own paper. The software does not capture, align, transcribe, or grade the notebook; reconciliation is the learner's labour and is itself part of the practice.

---

## 5 The Two Independent Axes

The Symbol Set and the Condition are independent.

- **Symbol Set** — gated by what the learner has claimed competence in. Begins with two symbols and grows only as the learner adds them. Unknown symbols never enter the stream.
- **Condition** — clean signal, static, fading, fist variation, tone variation, weak-signal emergence. Freely chosen by the learner at any time.

A learner with two symbols can practise under degraded conditions. A learner with the full alphabet can practise under perfect conditions. The axes do not constrain each other.

This independence resolves the apparent tension between minimal symbol introduction (per 3.5) and operational realism. They are not competing values; they are orthogonal axes the learner navigates independently.

---

## 6 The Notebook

The notebook is a halfway house between head copy and full transcription. It allows the learner to externalise partial understanding while remaining immersed in the auditory environment.

The notebook is not data entry. Copy does not require it to:

- synchronise with the audio timeline
- produce machine-readable entries
- enforce notation
- optimise transcription speed

The notebook supports:

- freeform capture
- personal shorthand
- confidence marks
- uncertainty notation
- fragmented reconstruction
- gradual recognition

Each learner develops their own notebook practice. Copy supports that emergence rather than constraining it. The reconciliation between the notebook and what was sent is performed by the learner, with the truth exposed by the software but not imposed by it.

---

## 7 Realistic Listening

The skills Copy trains are not specific to amateur radio.

Sustained attention under partial information, confidence under ambiguity, recovery from gaps, gradual reconciliation, and continued use despite incomplete understanding are competencies shared across demanding disciplines:

- emergency and crisis management
- aviation communications
- sonar operation
- intelligence analysis
- musical transcription
- language immersion
- air traffic control

In all of these, competence emerges not from perfect information but from the ability to keep operating when information is imperfect. Copy is a training environment for that posture, instantiated in CW because CW is a discipline where partial-information conditions are inherent rather than incidental.

---

## 8 Scope

Copy is:

- a listening environment for CW
- a tool for developing direct sound → meaning recognition
- a structure for deferred, honest verification
- a companion to a paper notebook

Copy is not:

- a CW transmission trainer (transmission is a separate motor skill)
- a Koch curriculum (Koch is a method Copy honours; it is not a syllabus Copy delivers)
- a scoring or progression system
- a leaderboard or community platform
- a mentor simulator

The goal is not successful character recognition.

The goal is sustained auditory fluency and confidence in real listening environments.
