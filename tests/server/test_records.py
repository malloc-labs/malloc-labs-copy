"""Tests for copy_653.server.records helpers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from copy_653.server import records as records_module
from copy_653.server.records import (
    MIN_SECONDS_PER_CLAIMED_SET,
    _next_koch_run_index,
    _next_symbol_evidence,
    _next_symbol_readiness,
    _resolve_session_gears,
    _seconds_on_claimed_set,
)


def _write_koch_json(target_dir: Path, name: str, payload: dict) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / name).write_text(json.dumps(payload))


def test_next_run_index_is_one_when_directory_missing(tmp_path: Path):
    assert _next_koch_run_index(tmp_path, "K M") == 1


def test_next_run_index_is_one_when_no_matching_records(tmp_path: Path):
    target = tmp_path / "koch-exercise"
    target.mkdir()
    # An unrelated claimed-set key should not increment the K M count.
    _write_koch_json(
        target,
        "koch-exercise-20260101T000000Z.json",
        {
            "mode": "koch-exercise",
            "claimed_set": ["K", "M", "U"],
            "generation": {"claimed_set_key": "K M U"},
        },
    )
    assert _next_koch_run_index(tmp_path, "K M") == 1


def test_next_run_index_counts_matching_records(tmp_path: Path):
    target = tmp_path / "koch-exercise"
    target.mkdir()
    _write_koch_json(
        target,
        "koch-exercise-20260101T000000Z.json",
        {
            "mode": "koch-exercise",
            "claimed_set": ["K", "M"],
            "generation": {"claimed_set_key": "K M"},
        },
    )
    _write_koch_json(
        target,
        "koch-exercise-20260102T000000Z.json",
        {
            "mode": "koch-exercise",
            "claimed_set": ["K", "M"],
            "generation": {"claimed_set_key": "K M"},
        },
    )
    assert _next_koch_run_index(tmp_path, "K M") == 3


def test_next_run_index_derives_key_from_claimed_set_for_legacy_records(tmp_path: Path):
    target = tmp_path / "koch-exercise"
    target.mkdir()
    # Schema 1.3-style record: no generation.claimed_set_key. The helper
    # must derive the key from claimed_set so legacy records still count.
    _write_koch_json(
        target,
        "koch-exercise-20251231T000000Z.json",
        {"mode": "koch-exercise", "claimed_set": ["M", "K"]},
    )
    assert _next_koch_run_index(tmp_path, "K M") == 2


def test_resolve_session_gears_returns_zeros_when_no_history(tmp_path: Path):
    # No prior records — every slot defaults to gear 0.
    assert _resolve_session_gears(tmp_path, "K M", exercise_count=5) == [0, 0, 0, 0, 0]


def test_resolve_session_gears_advances_band_after_three_strong_runs(tmp_path: Path):
    target = tmp_path / "koch-exercise"
    target.mkdir()

    def _session(stamp: str, fraction: float) -> dict:
        return {
            "schema_version": "2.0",
            "mode": "koch-exercise",
            "started_at": stamp,
            "claimed_set": ["K", "M"],
            "generation": {
                "claimed_set_key": "K M",
                "bands": [
                    {"index": 1, "gear": 0},
                    {"index": 2, "gear": 0},
                    {"index": 3, "gear": 0},
                    {"index": 4, "gear": 0},
                    {"index": 5, "gear": 0},
                ],
            },
            "exercises": [
                {
                    "index": i + 1,
                    "burden_band": i + 1,
                    "burden_score": 10 * (i + 1),
                    "analysis": {
                        "saved": True,
                        "combined_fraction": fraction,
                        "band_state": "exact" if fraction >= 1.0 else "low",
                    },
                }
                for i in range(5)
            ],
        }

    for idx, stamp in enumerate(
        [
            "2026-05-18T10:00:00.000Z",
            "2026-05-18T11:00:00.000Z",
            "2026-05-18T12:00:00.000Z",
        ]
    ):
        (target / f"koch-exercise-{idx}.json").write_text(json.dumps(_session(stamp, 1.0)))

    gears = _resolve_session_gears(tmp_path, "K M", exercise_count=5)
    # Three consecutive strong runs at every band: every slot advances to gear 1.
    assert gears == [1, 1, 1, 1, 1]


def test_next_run_index_skips_unreadable_and_non_koch_files(tmp_path: Path):
    target = tmp_path / "koch-exercise"
    target.mkdir()
    (target / "koch-exercise-broken.json").write_text("{not valid json")
    _write_koch_json(
        target,
        "koch-exercise-cadence.json",
        {"mode": "cadence-send", "claimed_set": ["K", "M"]},
    )
    assert _next_koch_run_index(tmp_path, "K M") == 1


# ---- per-claimed-set time floor (soft gate) --------------------------------


def _session_record(stamp: str, *, claimed_set_key: str, duration_seconds: float) -> dict:
    """Minimal koch-exercise record with controllable wall-clock duration."""
    start = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    end = start + timedelta(seconds=duration_seconds)
    return {
        "mode": "koch-exercise",
        "started_at": stamp,
        "ended_at": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "claimed_set": claimed_set_key.split(" "),
        "generation": {"claimed_set_key": claimed_set_key},
    }


def test_seconds_on_claimed_set_sums_matching_records():
    records = [
        _session_record("2026-05-18T10:00:00.000Z", claimed_set_key="K M", duration_seconds=300),
        _session_record("2026-05-18T11:00:00.000Z", claimed_set_key="K M", duration_seconds=600),
        _session_record("2026-05-19T10:00:00.000Z", claimed_set_key="K M U", duration_seconds=999),
    ]
    assert _seconds_on_claimed_set(records, claimed_set_key="K M") == 900
    assert _seconds_on_claimed_set(records, claimed_set_key="K M U") == 999


def test_seconds_on_claimed_set_skips_records_without_ended_at():
    records = [
        _session_record("2026-05-18T10:00:00.000Z", claimed_set_key="K M", duration_seconds=60),
        {
            "mode": "koch-exercise",
            "started_at": "2026-05-18T11:00:00.000Z",
            # ended_at intentionally missing — degrade to 0 contribution.
            "claimed_set": ["K", "M"],
            "generation": {"claimed_set_key": "K M"},
        },
    ]
    assert _seconds_on_claimed_set(records, claimed_set_key="K M") == 60


def test_seconds_on_claimed_set_derives_key_from_claimed_set_for_legacy():
    # Legacy record (no generation.claimed_set_key) still gets bucketed by
    # deriving the key from claimed_set, mirroring _next_koch_run_index.
    records = [
        {
            "mode": "koch-exercise",
            "started_at": "2025-12-31T10:00:00.000Z",
            "ended_at": "2025-12-31T10:05:00.000Z",
            "claimed_set": ["M", "K"],
        },
    ]
    assert _seconds_on_claimed_set(records, claimed_set_key="K M") == 300


def test_seconds_on_claimed_set_empty_key_returns_zero():
    records = [
        _session_record("2026-05-18T10:00:00.000Z", claimed_set_key="K M", duration_seconds=600),
    ]
    assert _seconds_on_claimed_set(records, claimed_set_key="") == 0.0


def test_next_symbol_readiness_blocked_by_time_floor_when_evidence_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Evidence analysis green-lights, but only 30 minutes on this set —
    # under the hour-long floor. Gate stays closed.
    monkeypatch.setattr(records_module, "is_ready_for_next_symbol", lambda *_, **__: True)
    target = tmp_path / "koch-exercise"
    target.mkdir()
    _write_koch_json(
        target,
        "koch-exercise-20260518T100000Z.json",
        _session_record("2026-05-18T10:00:00.000Z", claimed_set_key="K M", duration_seconds=1800),
    )
    assert _next_symbol_readiness(tmp_path, "K M") is False


def test_next_symbol_readiness_passes_when_evidence_and_time_both_met(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(records_module, "is_ready_for_next_symbol", lambda *_, **__: True)
    target = tmp_path / "koch-exercise"
    target.mkdir()
    _write_koch_json(
        target,
        "koch-exercise-20260518T100000Z.json",
        _session_record(
            "2026-05-18T10:00:00.000Z",
            claimed_set_key="K M",
            duration_seconds=MIN_SECONDS_PER_CLAIMED_SET,
        ),
    )
    assert _next_symbol_readiness(tmp_path, "K M") is True


def test_next_symbol_readiness_stays_closed_when_evidence_not_ready_even_above_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Hours of contact time but evidence analysis says no — the gate is
    # ANDed, not ORed: time alone never opens the nudge.
    monkeypatch.setattr(records_module, "is_ready_for_next_symbol", lambda *_, **__: False)
    target = tmp_path / "koch-exercise"
    target.mkdir()
    _write_koch_json(
        target,
        "koch-exercise-20260518T100000Z.json",
        _session_record(
            "2026-05-18T10:00:00.000Z",
            claimed_set_key="K M",
            duration_seconds=10 * MIN_SECONDS_PER_CLAIMED_SET,
        ),
    )
    assert _next_symbol_readiness(tmp_path, "K M") is False


def test_next_symbol_readiness_empty_key_returns_false(tmp_path: Path):
    assert _next_symbol_readiness(tmp_path, "") is False


# ---- evidence-only signal (drives the in-contention box) -------------------


def test_next_symbol_evidence_passes_through_band_evidence_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Empty records dir is fine — _next_symbol_evidence does not care
    # about time on set, only what the evidence analysis returns.
    monkeypatch.setattr(records_module, "is_ready_for_next_symbol", lambda *_, **__: True)
    assert _next_symbol_evidence(tmp_path, "K M") is True

    monkeypatch.setattr(records_module, "is_ready_for_next_symbol", lambda *_, **__: False)
    assert _next_symbol_evidence(tmp_path, "K M") is False


def test_next_symbol_evidence_ignores_time_floor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Even zero contact time is fine — that's the point: the box (which
    # this signal drives) is supposed to appear *before* the time floor
    # has been met, so the durability probe can run during the ramp.
    monkeypatch.setattr(records_module, "is_ready_for_next_symbol", lambda *_, **__: True)
    target = tmp_path / "koch-exercise"
    target.mkdir()
    _write_koch_json(
        target,
        "koch-exercise-20260518T100000Z.json",
        _session_record("2026-05-18T10:00:00.000Z", claimed_set_key="K M", duration_seconds=0),
    )
    assert _next_symbol_evidence(tmp_path, "K M") is True
    # And the full nudge gate stays closed at the same record — sanity
    # check that the two signals diverge as designed.
    assert _next_symbol_readiness(tmp_path, "K M") is False


def test_next_symbol_evidence_empty_key_returns_false(tmp_path: Path):
    assert _next_symbol_evidence(tmp_path, "") is False
