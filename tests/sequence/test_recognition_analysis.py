"""Tests for recognition windowing + per-symbol classification."""

from copy_653.sequence.recognition_analysis import (
    ANALYSIS_VERSION,
    MAX_GEAR,
    OUTCOME_CAUGHT_CORRECT,
    OUTCOME_CAUGHT_SUBSTITUTION,
    OUTCOME_CORRECT,
    OUTCOME_MISS,
    OUTCOME_SUBSTITUTION,
    REVIEW_ANALYSIS_VERSION,
    apply_acclimatisation_grace,
    attach_recognition_review_analysis,
    analyse_recognition_exercises,
    build_recognition_generation_profile,
    gear_for_recognition_set,
    latest_completed_set_gear_for_claimed_set,
    latest_gears_for_claimed_set,
    load_band_evidence,
    load_recognition_confusion,
    load_recognition_timing,
    load_set_evidence,
    recognition_review_analysis,
    resolve_gears,
    resolve_set_gear,
    window_exercise,
)


def _sym(symbol: str, t_on: float) -> dict:
    return {"symbol": symbol, "t_on": t_on, "t_off": t_on + 0.6}


def _utt(text: str, symbols: list[str], t: float) -> dict:
    return {"text": text, "symbols": symbols, "t": t}


def test_clean_correct_run():
    symbols = [_sym("K", 0.0), _sym("M", 5.0)]
    capture = [_utt("kilo", ["K"], 3.0), _utt("mike", ["M"], 8.0)]

    result = window_exercise(symbols, capture)

    assert result["version"] == ANALYSIS_VERSION
    assert result["committed_answer"] == "KM"
    assert result["committed_confusions"] == []
    assert result["caught_confusions"] == []
    assert result["ambiguous_lag"] is False
    assert [s["outcome"] for s in result["slots"]] == [OUTCOME_CORRECT, OUTCOME_CORRECT]


def test_committed_substitution():
    # Heard U, said R, no correction — a committed confusion.
    symbols = [_sym("U", 0.0)]
    capture = [_utt("romeo", ["R"], 3.0)]

    result = window_exercise(symbols, capture)

    assert result["committed_answer"] == "R"
    assert result["committed_confusions"] == [["U", "R"]]
    assert result["caught_confusions"] == []
    assert result["slots"][0]["outcome"] == OUTCOME_SUBSTITUTION


def test_caught_correct_single_utterance():
    # Heard U, said "romeo uniform" in one breath — corrected to truth.
    symbols = [_sym("U", 0.0)]
    capture = [_utt("romeo uniform", ["R", "U"], 4.0)]

    result = window_exercise(symbols, capture)

    slot = result["slots"][0]
    assert slot["tokens"] == ["R", "U"]
    assert slot["committed"] == "U"
    assert slot["superseded"] == ["R"]
    assert slot["outcome"] == OUTCOME_CAUGHT_CORRECT
    # The false start is preserved in the caught stream, never committed.
    assert result["committed_answer"] == "U"
    assert result["committed_confusions"] == []
    assert result["caught_confusions"] == [["U", "R"]]


def test_caught_correct_across_two_utterances():
    # Same correction, but spoken as two separate finals in one window.
    symbols = [_sym("U", 0.0), _sym("K", 6.0)]
    capture = [
        _utt("romeo", ["R"], 3.0),
        _utt("uniform", ["U"], 4.5),
        _utt("kilo", ["K"], 9.0),
    ]

    result = window_exercise(symbols, capture)

    assert [s["outcome"] for s in result["slots"]] == [
        OUTCOME_CAUGHT_CORRECT,
        OUTCOME_CORRECT,
    ]
    assert result["committed_answer"] == "UK"
    assert result["caught_confusions"] == [["U", "R"]]


def test_caught_substitution():
    # Corrected from one wrong symbol to another wrong symbol.
    symbols = [_sym("U", 0.0)]
    capture = [_utt("romeo kilo", ["R", "K"], 4.0)]

    result = window_exercise(symbols, capture)

    slot = result["slots"][0]
    assert slot["outcome"] == OUTCOME_CAUGHT_SUBSTITUTION
    assert slot["committed"] == "K"
    assert result["committed_confusions"] == [["U", "K"]]
    assert result["caught_confusions"] == [["U", "R"]]


def test_miss_window():
    symbols = [_sym("K", 0.0), _sym("M", 5.0)]
    capture = [_utt("kilo", ["K"], 3.0)]  # nothing for M

    result = window_exercise(symbols, capture)

    assert result["slots"][1]["outcome"] == OUTCOME_MISS
    assert result["slots"][1]["committed"] is None
    assert result["committed_answer"] == "K"


def test_pre_symbol_utterances_not_forced_onto_slot_one():
    symbols = [_sym("K", 5.0)]
    capture = [_utt("mike", ["M"], 1.0), _utt("kilo", ["K"], 8.0)]

    result = window_exercise(symbols, capture)

    assert len(result["pre_symbol"]) == 1
    assert result["pre_symbol"][0]["text"] == "mike"
    assert result["slots"][0]["committed"] == "K"
    assert result["slots"][0]["outcome"] == OUTCOME_CORRECT


def test_ambiguous_lag_flag():
    # Symbol 2's window is empty; symbol 3's window carries two tokens.
    # Structurally indistinguishable from a correction without care, so
    # the flag warns the next layer.
    symbols = [_sym("K", 0.0), _sym("M", 5.0), _sym("U", 10.0)]
    capture = [
        _utt("kilo", ["K"], 3.0),
        # nothing in M's window [5, 10)
        _utt("mike", ["M"], 12.0),
        _utt("uniform", ["U"], 13.0),
    ]

    result = window_exercise(symbols, capture)

    assert result["ambiguous_lag"] is True
    assert result["slots"][1]["outcome"] == OUTCOME_MISS


def test_unsorted_symbols_are_ordered_by_onset():
    symbols = [_sym("M", 5.0), _sym("K", 0.0)]
    capture = [_utt("kilo", ["K"], 3.0), _utt("mike", ["M"], 8.0)]

    result = window_exercise(symbols, capture)

    assert [s["truth"] for s in result["slots"]] == ["K", "M"]
    assert result["committed_answer"] == "KM"


def test_malformed_entries_are_skipped():
    symbols = [
        _sym("K", 0.0),
        {"symbol": "X"},  # no t_on
        "not a dict",
        _sym("M", 5.0),
    ]
    capture = [_utt("kilo", ["K"], 3.0), {"text": "junk"}, _utt("mike", ["M"], 8.0)]

    result = window_exercise(symbols, capture)

    assert [s["truth"] for s in result["slots"]] == ["K", "M"]
    assert result["committed_answer"] == "KM"


# ─── Real record fixtures (recognition-20260529T123631Z.json) ────────────────


def test_real_exercise_3_caught_correction():
    # Truth U K U U U; learner said "romeo uniform" on the third symbol.
    symbols = [
        _sym("U", 50.679),
        _sym("K", 55.2987),
        _sym("U", 59.9603),
        _sym("U", 64.5532),
        _sym("U", 69.1601),
    ]
    capture = [
        _utt("uniform", ["U"], 54.2905),
        _utt("kilo", ["K"], 58.3662),
        _utt("romeo uniform", ["R", "U"], 63.8903),
        _utt("uniform", ["U"], 68.4476),
        _utt("uniform", ["U"], 72.2853),
    ]

    result = window_exercise(symbols, capture)

    assert result["committed_answer"] == "UKUUU"
    assert result["committed_confusions"] == []
    assert result["caught_confusions"] == [["U", "R"]]
    assert result["ambiguous_lag"] is False
    assert result["slots"][2]["outcome"] == OUTCOME_CAUGHT_CORRECT


def test_real_exercise_2_committed_substitution():
    # Truth M U R M R; learner heard the U as R and did not correct.
    symbols = [
        _sym("M", 24.9799),
        _sym("U", 29.4767),
        _sym("R", 34.0596),
        _sym("M", 39.0796),
        _sym("R", 43.6162),
    ]
    capture = [
        _utt("mike", ["M"], 27.4021),
        _utt("romeo", ["R"], 32.442),
        _utt("romeo", ["R"], 37.0022),
        _utt("mike", ["M"], 41.5677),
        _utt("romeo", ["R"], 46.601),
    ]

    result = window_exercise(symbols, capture)

    assert result["committed_answer"] == "MRRMR"
    assert result["committed_confusions"] == [["U", "R"]]
    assert result["caught_confusions"] == []
    assert result["slots"][1]["outcome"] == OUTCOME_SUBSTITUTION


# ─── analyse_recognition_exercises (save-time per-exercise analysis) ──────────


def _flat_symbols(*per_exercise: list[tuple[str, float]]) -> list[dict]:
    """Build a flat record-shaped symbols list with exercise_index set."""
    out: list[dict] = []
    for ex_index, syms in enumerate(per_exercise, start=1):
        for symbol, t_on in syms:
            out.append({"symbol": symbol, "t_on": t_on, "exercise_index": ex_index})
    return out


def test_analyse_attaches_block_per_exercise_with_counts_and_streams():
    symbols = _flat_symbols(
        [("U", 0.0), ("K", 6.0), ("U", 12.0)],  # ex1: caught correct on slot3
        [("M", 20.0), ("U", 26.0)],  # ex2: committed substitution on slot2
    )
    exercises = [
        {
            "index": 1,
            "target": "U K U",
            "answer": "UKU",
            "voice_capture": [
                _utt("uniform", ["U"], 3.0),
                _utt("kilo", ["K"], 9.0),
                _utt("romeo uniform", ["R", "U"], 15.0),
            ],
        },
        {
            "index": 2,
            "target": "M U",
            "answer": "MR",
            "voice_capture": [
                _utt("mike", ["M"], 23.0),
                _utt("romeo", ["R"], 29.0),
            ],
        },
    ]

    result = analyse_recognition_exercises(exercises, symbols)

    a1 = result[0]["analysis"]
    assert a1["version"] == ANALYSIS_VERSION
    assert a1["has_evidence"] is True
    assert a1["committed_answer"] == "UKU"
    assert a1["method"] == "answer-alignment"
    assert a1["counts"] == {
        OUTCOME_CORRECT: 3,
        OUTCOME_SUBSTITUTION: 0,
        OUTCOME_CAUGHT_CORRECT: 0,
        OUTCOME_CAUGHT_SUBSTITUTION: 0,
        OUTCOME_MISS: 0,
    }
    assert a1["combined_fraction"] == 1.0
    assert a1["recognition_state"] == "exact"
    assert a1["band_state"] == "exact"
    assert a1["saved"] is True
    assert a1["caught_confusions"] == []
    assert a1["committed_confusions"] == []
    timing1 = result[0]["timing_analysis"]
    assert timing1["method"] == "onset-window"
    assert timing1["counts"][OUTCOME_CAUGHT_CORRECT] == 1
    assert timing1["caught_confusions"] == [["U", "R"]]

    a2 = result[1]["analysis"]
    assert a2["committed_answer"] == "MR"
    assert a2["committed_confusions"] == [["U", "R"]]
    assert a2["counts"][OUTCOME_SUBSTITUTION] == 1
    assert a2["combined_fraction"] == 0.5
    assert a2["recognition_state"] == "low"

    # Raw fields are left untouched by the rewrite.
    assert result[0]["answer"] == "UKU"
    assert result[0]["voice_capture"] == exercises[0]["voice_capture"]


def test_analyse_no_evidence_for_silent_exercise():
    symbols = _flat_symbols([("K", 0.0), ("M", 6.0)])
    exercises = [{"index": 1, "target": "K M", "answer": "", "voice_capture": []}]

    result = analyse_recognition_exercises(exercises, symbols)

    analysis = result[0]["analysis"]
    assert analysis["has_evidence"] is False
    assert analysis["recognition_state"] == "silent"
    assert analysis["committed_answer"] == ""
    assert analysis["counts"][OUTCOME_MISS] == 2
    assert analysis["committed_confusions"] == []
    assert analysis["caught_confusions"] == []


def test_analyse_missing_voice_capture_field_is_all_miss():
    symbols = _flat_symbols([("K", 0.0)])
    exercises = [{"index": 1, "target": "K", "answer": "K"}]  # no voice_capture key

    result = analyse_recognition_exercises(exercises, symbols)

    assert result[0]["analysis"]["has_evidence"] is True
    assert result[0]["analysis"]["counts"][OUTCOME_CORRECT] == 1
    assert result[0]["timing_analysis"]["has_evidence"] is False
    assert result[0]["timing_analysis"]["counts"][OUTCOME_MISS] == 1


def test_analyse_slots_are_lean_without_utterances():
    symbols = _flat_symbols([("K", 0.0)])
    exercises = [
        {"index": 1, "target": "K", "voice_capture": [_utt("kilo", ["K"], 3.0)]},
    ]

    slots = analyse_recognition_exercises(exercises, symbols)[0]["timing_analysis"]["slots"]

    assert slots[0] == {
        "index": 1,
        "truth": "K",
        "t_on": 0.0,
        "tokens": ["K"],
        "committed": "K",
        "superseded": [],
        "outcome": OUTCOME_CORRECT,
    }
    assert "utterances" not in slots[0]


def test_analyse_distributes_word_response_across_grouped_symbols():
    symbols = [
        {"symbol": "K", "t_on": 0.0, "exercise_index": 1, "word_index": 1, "word": "KM"},
        {"symbol": "M", "t_on": 1.5, "exercise_index": 1, "word_index": 1, "word": "KM"},
    ]
    exercises = [
        {
            "index": 1,
            "target": "KM",
            "voice_capture": [_utt("kilo mike", ["K", "M"], 4.0)],
        },
    ]

    result = analyse_recognition_exercises(exercises, symbols)[0]
    analysis = result["analysis"]
    timing = result["timing_analysis"]

    assert analysis["committed_answer"] == ""
    assert analysis["counts"][OUTCOME_MISS] == 2
    assert timing["committed_answer"] == "KM"
    assert timing["counts"][OUTCOME_CORRECT] == 2
    assert timing["counts"][OUTCOME_MISS] == 0
    assert [slot["tokens"] for slot in timing["slots"]] == [["K"], ["M"]]
    assert (
        analyse_recognition_exercises(
            [{**exercises[0], "answer": "KM"}],
            symbols,
        )[0][
            "analysis"
        ]["committed_answer"]
        == "KM"
    )


def test_review_analysis_softens_strict_substitutions_when_timing_shows_recovery():
    exercise = {
        "index": 4,
        "target": "RR KK",
        "answer": "KKRRK0",
        "analysis": {
            "version": ANALYSIS_VERSION,
            "method": "answer-alignment",
            "has_evidence": True,
            "committed_answer": "KKRRK0",
            "counts": {
                OUTCOME_CORRECT: 0,
                OUTCOME_SUBSTITUTION: 4,
                OUTCOME_CAUGHT_CORRECT: 0,
                OUTCOME_CAUGHT_SUBSTITUTION: 0,
                OUTCOME_MISS: 0,
            },
            "combined_fraction": 0.0,
            "recognition_state": "low",
            "committed_confusions": [["R", "K"], ["R", "K"], ["K", "R"], ["K", "R"]],
            "caught_confusions": [],
            "slots": [_slot("R", "K"), _slot("R", "K"), _slot("K", "R"), _slot("K", "R")],
        },
        "timing_analysis": {
            "version": ANALYSIS_VERSION,
            "method": "onset-window",
            "has_evidence": True,
            "counts": {
                OUTCOME_CORRECT: 0,
                OUTCOME_SUBSTITUTION: 0,
                OUTCOME_CAUGHT_CORRECT: 1,
                OUTCOME_CAUGHT_SUBSTITUTION: 1,
                OUTCOME_MISS: 2,
            },
            "caught_confusions": [["K", "R"], ["K", "R"]],
            "ambiguous_lag": True,
        },
    }

    result = recognition_review_analysis(exercise)

    assert result["review_version"] == REVIEW_ANALYSIS_VERSION
    assert result["recovery_softened"] is True
    assert result["softened_substitutions"] == 4
    assert result["counts"][OUTCOME_SUBSTITUTION] == 0
    assert result["counts"][OUTCOME_CAUGHT_SUBSTITUTION] == 4
    assert result["committed_confusions"] == []
    assert result["softened_committed_confusions"] == [
        ["R", "K"],
        ["R", "K"],
        ["K", "R"],
        ["K", "R"],
    ]
    assert result["caught_confusions"] == [["K", "R"], ["K", "R"]]
    assert exercise["analysis"]["counts"][OUTCOME_SUBSTITUTION] == 4


def test_attach_recognition_review_analysis_adds_derived_blocks_without_mutating_record():
    record = _record(
        "K M R U",
        {
            "version": ANALYSIS_VERSION,
            "has_evidence": True,
            "counts": {
                OUTCOME_CORRECT: 0,
                OUTCOME_SUBSTITUTION: 1,
                OUTCOME_CAUGHT_CORRECT: 0,
                OUTCOME_CAUGHT_SUBSTITUTION: 0,
                OUTCOME_MISS: 0,
            },
            "committed_confusions": [["U", "R"]],
            "caught_confusions": [],
        },
    )
    record["exercises"][0]["timing_analysis"] = {
        "has_evidence": True,
        "caught_confusions": [["U", "R"]],
    }

    result = attach_recognition_review_analysis(record)

    assert "review_analysis" not in record["exercises"][0]
    assert result["exercises"][0]["review_analysis"]["recovery_softened"] is True


# ─── load_recognition_confusion (aggregation across records) ─────────────────


def _record(claimed_set_key: str, *exercise_analyses: dict) -> dict:
    return {
        "mode": "recognition",
        "generation": {"claimed_set_key": claimed_set_key},
        "exercises": [{"index": i + 1, "analysis": a} for i, a in enumerate(exercise_analyses)],
    }


def _analysis(*, committed=(), caught=(), has_evidence=True) -> dict:
    return {
        "version": ANALYSIS_VERSION,
        "has_evidence": has_evidence,
        "committed_confusions": [list(p) for p in committed],
        "caught_confusions": [list(p) for p in caught],
    }


def test_confusion_keeps_committed_and_caught_separate():
    records = [
        _record(
            "K M R U",
            _analysis(committed=[("U", "R")]),
            _analysis(caught=[("U", "R")]),
            _analysis(committed=[("U", "R"), ("K", "M")]),
        ),
    ]

    result = load_recognition_confusion(records, claimed_set_key="K M R U")

    assert result["exercises_used"] == 3
    assert [
        {"target": item["target"], "typed": item["typed"], "count": item["count"]}
        for item in result["committed_substitutions"]
    ] == [
        {"target": "U", "typed": "R", "count": 2},
        {"target": "K", "typed": "M", "count": 1},
    ]
    assert [
        {"target": item["target"], "typed": item["typed"], "count": item["count"]}
        for item in result["caught_substitutions"]
    ] == [{"target": "U", "typed": "R", "count": 1}]


def test_confusion_uses_review_softening_for_recovered_substitutions():
    record = {
        "mode": "recognition",
        "generation": {"claimed_set_key": "K M R U"},
        "exercises": [
            {
                "index": 1,
                "analysis": {
                    "version": ANALYSIS_VERSION,
                    "has_evidence": True,
                    "counts": {
                        OUTCOME_CORRECT: 0,
                        OUTCOME_SUBSTITUTION: 2,
                        OUTCOME_CAUGHT_CORRECT: 0,
                        OUTCOME_CAUGHT_SUBSTITUTION: 0,
                        OUTCOME_MISS: 0,
                    },
                    "committed_confusions": [["R", "K"], ["R", "K"]],
                    "caught_confusions": [],
                    "slots": [_slot("R", "K"), _slot("R", "K")],
                },
                "timing_analysis": {
                    "has_evidence": True,
                    "caught_confusions": [["R", "K"], ["R", "K"]],
                },
            }
        ],
    }

    result = load_recognition_confusion([record], claimed_set_key="K M R U")

    assert result["exercises_used"] == 1
    assert result["committed_substitutions"] == []
    assert [
        {"target": item["target"], "typed": item["typed"], "count": item["count"]}
        for item in result["caught_substitutions"]
    ] == [{"target": "R", "typed": "K", "count": 2}]


def test_confusion_ignores_other_claimed_sets_and_no_evidence():
    records = [
        _record("K M R U", _analysis(committed=[("U", "R")])),
        _record("A B", _analysis(committed=[("A", "B")])),  # different set
        _record("K M R U", _analysis(committed=[("M", "K")], has_evidence=False)),  # silent
    ]

    result = load_recognition_confusion(records, claimed_set_key="K M R U")

    assert result["exercises_used"] == 1
    assert [
        {"target": item["target"], "typed": item["typed"], "count": item["count"]}
        for item in result["committed_substitutions"]
    ] == [{"target": "U", "typed": "R", "count": 1}]
    assert result["caught_substitutions"] == []


def test_confusion_empty_when_no_matching_records():
    result = load_recognition_confusion([], claimed_set_key="K M R U")

    assert result == {
        "claimed_set_key": "K M R U",
        "exercises_used": 0,
        "trend_window_size": 20,
        "recent_exercises_used": 0,
        "previous_exercises_used": 0,
        "committed_substitutions": [],
        "caught_substitutions": [],
    }


def _slot(truth: str, committed: str | None = None) -> dict:
    return {
        "truth": truth,
        "committed": committed,
        "tokens": [committed] if committed is not None else [],
    }


def _analysis_with_slots(*, committed=(), slots=()) -> dict:
    analysis = _analysis(committed=committed)
    analysis["slots"] = [dict(slot) for slot in slots]
    return analysis


def test_confusion_reports_recent_previous_rates_and_trend():
    records = [
        _record(
            "K M R U",
            _analysis_with_slots(
                committed=[("K", "R")],
                slots=[_slot("K", "R"), _slot("U", "U")],
            ),
        )
        | {"started_at": "2026-05-31T12:00:00Z"},
        _record(
            "K M R U",
            _analysis_with_slots(slots=[_slot("K", "K"), _slot("U", "U")]),
        )
        | {"started_at": "2026-05-31T11:00:00Z"},
        _record(
            "K M R U",
            _analysis_with_slots(
                committed=[("K", "R"), ("K", "R")],
                slots=[_slot("K", "R"), _slot("K", "R")],
            ),
        )
        | {"started_at": "2026-05-31T10:00:00Z"},
    ]

    result = load_recognition_confusion(
        records,
        claimed_set_key="K M R U",
        trend_window_size=2,
    )

    assert result["recent_exercises_used"] == 2
    assert result["previous_exercises_used"] == 1
    assert result["committed_substitutions"][0] == {
        "target": "K",
        "typed": "R",
        "count": 3,
        "recent_count": 1,
        "recent_total": 2,
        "recent_rate": 0.5,
        "previous_count": 2,
        "previous_total": 2,
        "previous_rate": 1.0,
        "trend": "improving",
    }


# ─── load_recognition_timing (response latency across records) ───────────────


def _timing_record(
    *,
    started_at: str,
    claimed_set_key: str = "K M R U",
    gear: int = 1,
    target: str = "RK",
    response_t: float = 4.6,
    first_partial_t: float | None = None,
    fraction: float = 1.0,
    committed=(),
    miss_count: int = 0,
) -> dict:
    symbols = [
        {
            "symbol": symbol,
            "t_on": idx * 1.0,
            "t_off": idx * 1.0 + 0.5,
            "exercise_index": 1,
            "word": target,
        }
        for idx, symbol in enumerate(target)
    ]
    return {
        "mode": "recognition",
        "started_at": started_at,
        "generation": {
            "claimed_set_key": claimed_set_key,
            "recognition": {"recognition_time_ms": 1500},
        },
        "symbols": symbols,
        "exercises": [
            {
                "index": 1,
                "target": " ".join(target),
                "gear": gear,
                "answer": target,
                "voice_capture": [
                    _utt(target.lower(), list(target), response_t)
                    | ({"first_partial_t": first_partial_t} if first_partial_t is not None else {})
                ],
                "analysis": {
                    "has_evidence": True,
                    "combined_fraction": fraction,
                    "committed_confusions": [list(p) for p in committed],
                    "counts": {OUTCOME_MISS: miss_count},
                },
            }
        ],
    }


def test_recognition_timing_groups_targets_and_measures_after_target_end():
    records = [
        _timing_record(started_at="2026-06-01T10:00:00Z", response_t=4.6),
        _timing_record(
            started_at="2026-06-01T09:00:00Z", response_t=3.6, committed=[("K", "M")], fraction=0.5
        ),
        _timing_record(
            started_at="2026-06-01T08:00:00Z", target="RU", response_t=3.0, miss_count=1
        ),
    ]

    result = load_recognition_timing(records, claimed_set_key="K M R U")

    assert result["exercises_used"] == 3
    assert result["targets"][0] == {
        "gear": 1,
        "target": "RK",
        "count": 2,
        "median_ms": 2600,
        "recent_count": 2,
        "recent_median_ms": 2600,
        "previous_count": 0,
        "previous_median_ms": None,
        "trend": "insufficient",
        "correct_count": 1,
        "confused_count": 1,
        "missed_count": 0,
        "late_count": 2,
    }


def test_recognition_timing_reports_recent_previous_trend():
    records = [
        _timing_record(started_at="2026-06-01T12:00:00Z", response_t=3.0),
        _timing_record(started_at="2026-06-01T11:00:00Z", response_t=3.2),
        _timing_record(started_at="2026-06-01T10:00:00Z", response_t=4.0),
        _timing_record(started_at="2026-06-01T09:00:00Z", response_t=4.2),
    ]

    result = load_recognition_timing(
        records,
        claimed_set_key="K M R U",
        trend_window_size=2,
    )

    row = result["targets"][0]
    assert row["recent_median_ms"] == 1600
    assert row["previous_median_ms"] == 2600
    assert row["trend"] == "improving"


def test_recognition_timing_prefers_first_partial_for_new_records():
    records = [
        _timing_record(
            started_at="2026-06-01T12:00:00Z",
            response_t=5.0,
            first_partial_t=2.4,
        ),
    ]

    result = load_recognition_timing(records, claimed_set_key="K M R U")

    assert result["targets"][0]["median_ms"] == 900


def test_recognition_timing_uses_per_symbol_units_for_new_gear_zero_records():
    record = _timing_record(
        started_at="2026-06-01T12:00:00Z",
        gear=0,
        target="KR",
        response_t=4.0,
    )
    exercise = record["exercises"][0]
    exercise["voice_capture"][0]["symbol_events"] = [
        {"index": 1, "symbol": "K", "t": 1.0, "source": "partial"},
        {"index": 2, "symbol": "R", "t": 2.3, "source": "partial"},
    ]
    exercise["analysis"]["slots"] = [
        {"index": 1, "truth": "K", "outcome": OUTCOME_CORRECT},
        {"index": 2, "truth": "R", "outcome": OUTCOME_CORRECT},
    ]

    result = load_recognition_timing([record], claimed_set_key="K M R U")

    rows = {row["target"]: row for row in result["targets"]}
    assert rows["K"]["median_ms"] == 500
    assert rows["R"]["median_ms"] == 800
    assert "KR" not in rows


# ─── Recognition progression evidence ────────────────────────────────────────


def _progression_record(started_at: str, gear: int, fraction: float) -> dict:
    return {
        "mode": "recognition",
        "started_at": started_at,
        "generation": {
            "claimed_set_key": "K M",
            "bands": [{"index": 1, "gear": gear}],
        },
        "exercises": [
            {
                "index": 1,
                "burden_band": 1,
                "gear": gear,
                "analysis": {
                    "has_evidence": True,
                    "combined_fraction": fraction,
                    "recognition_state": "exact" if fraction >= 1.0 else "low",
                },
            }
        ],
    }


def test_generation_profile_records_per_slot_gears():
    profile = build_recognition_generation_profile(
        claimed_set=("K", "M"),
        exercise_count=3,
        gears=[0, 1, 2],
    )

    assert profile["profile_version"] == "recognition-progression-v1"
    assert profile["claimed_set_key"] == "K M"
    assert profile["gear"] == 0
    assert profile["bands"] == [
        {"index": 1, "gear": 0},
        {"index": 2, "gear": 1},
        {"index": 3, "gear": 2},
    ]


def _recognition_set_record(
    *,
    set_id: str,
    set_session: int,
    gear: int,
    fraction: float,
) -> dict:
    return {
        "mode": "recognition",
        "started_at": f"2026-05-18T13:{set_session:02d}:00Z",
        "generation": {
            "claimed_set_key": "K M",
            "set_id": set_id,
            "set_session": set_session,
            "gear": gear,
            "bands": [{"index": index, "gear": gear} for index in range(1, 6)],
        },
        "exercises": [
            {
                "index": index,
                "burden_band": index,
                "gear": gear,
                "analysis": {
                    "has_evidence": fraction > 0,
                    "combined_fraction": fraction,
                    "recognition_state": "exact" if fraction >= 1.0 else "silent",
                },
            }
            for index in range(1, 6)
        ],
    }


def test_acclimatisation_grace_marks_set_three_first_retry_recovery():
    exercises = [
        {
            "index": 1,
            "target": "KM UR",
            "analysis": {
                "has_evidence": True,
                "combined_fraction": 0.25,
                "recognition_state": "low",
            },
        },
        {
            "index": 2,
            "target": "KM UR",
            "analysis": {
                "has_evidence": True,
                "combined_fraction": 1.0,
                "recognition_state": "exact",
            },
        },
    ]

    result = apply_acclimatisation_grace(exercises, set_session=3)

    assert result[0]["analysis"]["acclimatisation_grace"] is True
    assert result[0]["analysis"]["evidence_weight"] == "soft"
    assert result[0]["analysis"]["progression_excluded"] is True
    assert result[0]["analysis"]["combined_fraction"] == 0.25


def test_acclimatisation_grace_does_not_mark_set_two():
    exercises = [
        {
            "index": 1,
            "target": "KM UR",
            "analysis": {"combined_fraction": 0.25, "recognition_state": "low"},
        },
        {
            "index": 2,
            "target": "KM UR",
            "analysis": {"combined_fraction": 1.0, "recognition_state": "exact"},
        },
    ]

    assert (
        "acclimatisation_grace"
        not in apply_acclimatisation_grace(
            exercises,
            set_session=2,
        )[
            0
        ]["analysis"]
    )


def test_recognition_set_evidence_advances_after_completed_strong_set():
    records = [
        _recognition_set_record(set_id="set-a", set_session=session, gear=0, fraction=1.0)
        for session in range(1, 9)
    ]

    evidence = load_set_evidence(records, claimed_set_key="K M")

    assert evidence["set_count"] == 1
    assert evidence["strong_streak"] == 1
    assert latest_completed_set_gear_for_claimed_set(records, claimed_set_key="K M") == 0
    assert resolve_set_gear(evidence, current_gear=0) == 1


def test_recognition_set_evidence_ignores_incomplete_set_for_progression():
    records = [
        _recognition_set_record(set_id="set-a", set_session=session, gear=0, fraction=1.0)
        for session in range(1, 8)
    ]

    evidence = load_set_evidence(records, claimed_set_key="K M")

    assert evidence["set_count"] == 0
    assert evidence["strong_streak"] == 0
    assert resolve_set_gear(evidence, current_gear=0) == 0


def test_recognition_set_evidence_counts_silent_sessions_against_progression():
    records = [
        _recognition_set_record(set_id="set-a", set_session=session, gear=1, fraction=1.0)
        for session in range(1, 8)
    ]
    records.append(_recognition_set_record(set_id="set-a", set_session=8, gear=1, fraction=0.0))

    evidence = load_set_evidence(records, claimed_set_key="K M")

    assert evidence["recent_fractions"] == [0.875]
    assert evidence["strong_streak"] == 0
    assert resolve_set_gear(evidence, current_gear=1) == 1


def test_recognition_set_evidence_softens_first_exercise_acclimatisation_recovery():
    records = [
        _recognition_set_record(set_id="set-a", set_session=session, gear=1, fraction=1.0)
        for session in range(1, 9)
    ]
    for record in records:
        for exercise in record["exercises"]:
            exercise["target"] = "KM UR"
    session_three = records[2]
    session_three["exercises"][0]["analysis"]["combined_fraction"] = 0.25
    session_three["exercises"][0]["analysis"]["recognition_state"] = "low"
    session_three["exercises"][1]["analysis"]["combined_fraction"] = 1.0
    session_three["exercises"][1]["analysis"]["recognition_state"] = "exact"

    evidence = load_set_evidence(records, claimed_set_key="K M")

    assert evidence["recent_fractions"] == [1.0]
    assert evidence["strong_streak"] == 1


def test_recognition_set_gear_holds_after_one_low_set():
    records = [
        _recognition_set_record(set_id="set-a", set_session=session, gear=1, fraction=0.0)
        for session in range(1, 9)
    ]

    evidence = load_set_evidence(records, claimed_set_key="K M")

    assert evidence["recent_fractions"] == [0.0]
    assert evidence["low_streak"] == 1
    assert resolve_set_gear(evidence, current_gear=1) == 1


def test_recognition_set_gear_drops_after_two_low_sets():
    records = [
        _recognition_set_record(set_id=set_id, set_session=session, gear=1, fraction=0.0)
        for set_id in ("set-a", "set-b")
        for session in range(1, 9)
    ]

    evidence = load_set_evidence(records, claimed_set_key="K M")

    assert evidence["recent_fractions"] == [0.0, 0.0]
    assert evidence["low_streak"] == 2
    assert resolve_set_gear(evidence, current_gear=1) == 0


def test_recognition_set_gear_can_be_reused_inside_active_set():
    records = [
        _recognition_set_record(set_id="set-a", set_session=session, gear=2, fraction=0.5)
        for session in range(1, 3)
    ]

    assert gear_for_recognition_set(records, claimed_set_key="K M", set_id="set-a") == 2


def test_load_band_evidence_and_resolve_gears_for_recognition():
    records = [
        _progression_record("2026-05-18T13:00:00Z", 0, 1.0),
        _progression_record("2026-05-18T13:10:00Z", 0, 1.0),
        _progression_record("2026-05-18T13:20:00Z", 0, 1.0),
    ]

    evidence = load_band_evidence(records, claimed_set_key="K M")

    assert evidence["bands"][0]["burden_band"] == 1
    assert evidence["bands"][0]["strong_streak"] == 3
    assert latest_gears_for_claimed_set(records, claimed_set_key="K M") == {1: 0}
    assert resolve_gears(evidence, current_gears={1: 0}) == {1: 1}


def test_recognition_gear_shift_is_single_step_and_capped():
    records = [
        _progression_record("2026-05-18T13:00:00Z", MAX_GEAR, 1.0),
        _progression_record("2026-05-18T13:10:00Z", MAX_GEAR, 1.0),
        _progression_record("2026-05-18T13:20:00Z", MAX_GEAR, 1.0),
    ]

    evidence = load_band_evidence(records, claimed_set_key="K M")

    assert resolve_gears(evidence, current_gears={1: MAX_GEAR}) == {1: MAX_GEAR}
