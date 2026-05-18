"""Tests for copy_653.server.records helpers."""

from __future__ import annotations

import json
from pathlib import Path

from copy_653.server.records import _next_koch_run_index


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
