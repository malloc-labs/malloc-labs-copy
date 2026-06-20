from copy_653.server.key_training_recommendations import build_key_training_recommendations
from copy_653.server.record_api import _enrich_key_training_record


def test_enrich_key_training_record_derives_review_metrics():
    entry = {}
    _enrich_key_training_record(
        {
            "training_mode": "intervals",
            "session_status": "completed",
            "sent": [{"symbol": "K"}, {"symbol": "R"}],
            "key_events": [{"kind": "dit"}],
            "attempts": [
                {
                    "exercise_index": 1,
                    "target_symbol": "K",
                    "result": "accepted",
                    "action": "advance",
                },
                {
                    "exercise_index": 1,
                    "target_symbol": "R",
                    "result": "accepted",
                    "action": "complete-exercise",
                },
                {
                    "exercise_index": 2,
                    "target_symbol": "R",
                    "result": "wrong-symbol",
                    "action": "taint-line",
                },
                {
                    "exercise_index": 2,
                    "target_symbol": "R",
                    "result": "timing-fail",
                    "action": "restart-line",
                },
                {
                    "exercise_index": 2,
                    "target_symbol": "R",
                    "result": "accepted",
                    "action": "complete-session",
                },
            ],
        },
        entry,
    )

    assert entry["training_mode"] == "intervals"
    assert entry["session_status"] == "completed"
    assert entry["source_symbols"] == []
    assert entry["decoded_send_count"] == 2
    assert entry["key_event_count"] == 1
    assert entry["scored_event_count"] == 5
    assert entry["attempt_count"] == 5
    assert entry["fault_count"] == 2
    assert entry["timing_fault_count"] == 1
    assert entry["wrong_symbol_count"] == 1
    assert entry["restart_count"] == 1
    assert entry["completed_exercise_count"] == 2
    assert entry["clean_exercise_count"] == 1
    assert entry["repeated_exercise_count"] == 1
    assert entry["exercise_attempt_count"] == 3
    assert entry["fault_counts"] == {"R": 2}
    assert entry["hardest_symbol"] == "R"
    assert entry["hardest_symbol_faults"] == 2


def test_enrich_key_training_record_exposes_source_symbols_for_calendar():
    entry = {}
    _enrich_key_training_record(
        {
            "training_mode": "scales",
            "session_status": "completed",
            "source_symbols": ["K", "M", "U", "R", "E"],
            "attempts": [],
        },
        entry,
    )

    assert entry["source_symbols"] == ["K", "M", "U", "R", "E"]


def test_enrich_key_training_record_reports_active_training_seconds():
    entry = {}
    _enrich_key_training_record(
        {
            "training_mode": "scales",
            "session_status": "abandoned",
            "attempts": [
                {"started_at": 100.0, "ended_at": 101.0},
                # A normal recovery gap counts.
                {"started_at": 106.0, "ended_at": 107.0},
                # A long idle gap is capped at 10 seconds.
                {"started_at": 167.0, "ended_at": 168.5},
            ],
        },
        entry,
    )

    assert entry["active_training_seconds"] == 18.5


def test_key_training_recommendations_prioritise_recent_faults_and_confusions():
    result = build_key_training_recommendations(
        [
            {
                "mode": "key-training",
                "started_at": "2026-06-19T12:00:00.000Z",
                "attempts": [
                    {
                        "target_symbol": "R",
                        "sent_symbol": "U",
                        "result": "wrong-symbol",
                        "action": "taint-line",
                    },
                    {
                        "target_symbol": "R",
                        "sent_symbol": "R",
                        "result": "timing-fail",
                        "action": "restart-line",
                    },
                    {
                        "target_symbol": "K",
                        "sent_symbol": "K",
                        "result": "accepted",
                        "action": "advance",
                    },
                    {
                        "target_symbol": "M",
                        "sent_symbol": "M",
                        "result": "accepted",
                        "action": "advance",
                    },
                ],
            }
        ]
    )

    assert result["has_evidence"] is True
    assert result["sessions_seen"] == 1
    assert result["sessions_used"] == 1
    assert result["attempt_count"] == 4
    assert result["focus_symbols"][0]["symbol"] == "R"
    assert result["focus_symbols"][0]["wrong_symbols"] == 1
    assert result["focus_symbols"][0]["timing_faults"] == 1
    assert result["focus_symbols"][0]["restarts"] == 1
    assert result["confusions"][0] == {
        "target": "R",
        "sent": "U",
        "count": 1.0,
        "score": 1.1,
    }


def test_key_training_recommendations_do_not_turn_clean_symbols_into_focus():
    result = build_key_training_recommendations(
        [
            {
                "mode": "key-training",
                "started_at": "2026-06-19T12:00:00.000Z",
                "attempts": [
                    *[
                        {
                            "target_symbol": "K",
                            "sent_symbol": "K",
                            "result": "accepted",
                            "action": "advance",
                        }
                        for _ in range(12)
                    ],
                    {
                        "target_symbol": "U",
                        "sent_symbol": "I",
                        "result": "wrong-symbol",
                        "action": "taint-line",
                    },
                ],
            }
        ]
    )

    assert [entry["symbol"] for entry in result["focus_symbols"]] == ["U"]
