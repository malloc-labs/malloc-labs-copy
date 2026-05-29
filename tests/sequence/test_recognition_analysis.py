"""Tests for recognition windowing + per-symbol classification."""

from copy_653.sequence.recognition_analysis import (
    ANALYSIS_VERSION,
    OUTCOME_CAUGHT_CORRECT,
    OUTCOME_CAUGHT_SUBSTITUTION,
    OUTCOME_CORRECT,
    OUTCOME_MISS,
    OUTCOME_SUBSTITUTION,
    analyse_recognition_exercises,
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
    assert a1["counts"] == {
        OUTCOME_CORRECT: 2,
        OUTCOME_SUBSTITUTION: 0,
        OUTCOME_CAUGHT_CORRECT: 1,
        OUTCOME_CAUGHT_SUBSTITUTION: 0,
        OUTCOME_MISS: 0,
    }
    assert a1["caught_confusions"] == [["U", "R"]]
    assert a1["committed_confusions"] == []

    a2 = result[1]["analysis"]
    assert a2["committed_answer"] == "MR"
    assert a2["committed_confusions"] == [["U", "R"]]
    assert a2["counts"][OUTCOME_SUBSTITUTION] == 1

    # Raw fields are left untouched by the rewrite.
    assert result[0]["answer"] == "UKU"
    assert result[0]["voice_capture"] == exercises[0]["voice_capture"]


def test_analyse_no_evidence_for_silent_exercise():
    symbols = _flat_symbols([("K", 0.0), ("M", 6.0)])
    exercises = [{"index": 1, "target": "K M", "answer": "", "voice_capture": []}]

    result = analyse_recognition_exercises(exercises, symbols)

    analysis = result[0]["analysis"]
    assert analysis["has_evidence"] is False
    assert analysis["committed_answer"] == ""
    assert analysis["counts"][OUTCOME_MISS] == 2
    assert analysis["committed_confusions"] == []
    assert analysis["caught_confusions"] == []


def test_analyse_missing_voice_capture_field_is_all_miss():
    symbols = _flat_symbols([("K", 0.0)])
    exercises = [{"index": 1, "target": "K", "answer": "K"}]  # no voice_capture key

    result = analyse_recognition_exercises(exercises, symbols)

    assert result[0]["analysis"]["has_evidence"] is False
    assert result[0]["analysis"]["counts"][OUTCOME_MISS] == 1


def test_analyse_slots_are_lean_without_utterances():
    symbols = _flat_symbols([("K", 0.0)])
    exercises = [
        {"index": 1, "target": "K", "voice_capture": [_utt("kilo", ["K"], 3.0)]},
    ]

    slots = analyse_recognition_exercises(exercises, symbols)[0]["analysis"]["slots"]

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
