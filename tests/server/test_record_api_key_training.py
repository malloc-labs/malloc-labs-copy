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
