from copy_653.session.compat import backfill_copy_key_record, backfill_copy_key_records


def _sent(symbol: str, pattern: str, started_at: float, ended_at: float, leading_gap: str) -> dict:
    return {
        "symbol": symbol,
        "pattern": pattern,
        "started_at": started_at,
        "ended_at": ended_at,
        "leading_gap": leading_gap,
    }


def test_backfill_copy_key_record_adds_missing_analysis():
    record = {
        "mode": "copy-key",
        "audio": {"character_speed_wpm": 20},
        "exercises": [{"index": 1, "target": "KM", "burden_band": 1}],
        "sent": [
            _sent("K", "-.-", 1.0, 1.54, "none"),
            _sent("M", "--", 1.72, 2.14, "character"),
        ],
        "key_events": [],
    }

    updated = backfill_copy_key_record(record)

    assert updated is record
    exercise = updated["exercises"][0]
    assert [event["symbol"] for event in exercise["attempts"][0]["events"]] == ["K", "M"]
    assert exercise["analysis"]["saved"] is True
    assert exercise["analysis"]["symbol_fraction"] == 1.0


def test_backfill_copy_key_record_is_idempotent_when_analysis_is_saved():
    analysed_exercises = [
        {
            "index": 1,
            "target": "K",
            "analysis": {"saved": True, "sentinel": "preserved"},
        }
    ]
    record = {
        "mode": "copy-key",
        "audio": {"character_speed_wpm": 20},
        "exercises": analysed_exercises,
        "sent": [],
        "key_events": [],
    }

    updated = backfill_copy_key_record(record)

    assert updated is record
    assert updated["exercises"] is analysed_exercises
    assert updated["exercises"][0]["analysis"]["sentinel"] == "preserved"


def test_backfill_copy_key_records_returns_original_batch():
    records = [
        {
            "mode": "copy-key",
            "audio": {"character_speed_wpm": 20},
            "exercises": [{"index": 1, "target": "K"}],
            "sent": [_sent("K", "-.-", 1.0, 1.54, "none")],
            "key_events": [],
        }
    ]

    updated = backfill_copy_key_records(records)

    assert updated is records
    assert records[0]["exercises"][0]["analysis"]["saved"] is True
