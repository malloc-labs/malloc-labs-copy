from copy_653.sequence.exercise_analysis import (
    MAX_RST_STEP,
    RST_WINDOW_TOP,
    RST_WINDOW_WIDTH,
    is_eligible_for_axis,
    latest_rst_steps_for_claimed_set,
    load_rst_axis_evidence,
    resolve_rst_steps,
    rst_window_for_step,
)


def _session(
    started_at: str,
    *,
    claimed_set_key: str = "K M U",
    bands: list[dict] | None = None,
    rst_steps: list[dict] | None = None,
    exercises: list[dict] | None = None,
) -> dict:
    generation: dict = {"claimed_set_key": claimed_set_key}
    if bands is not None:
        generation["bands"] = bands
    if rst_steps is not None:
        generation["rst_steps"] = rst_steps
    return {
        "mode": "koch-exercise",
        "started_at": started_at,
        "generation": generation,
        "exercises": exercises or [],
    }


def _ex(burden_band: int, fraction: float, s: int | None, t: int | None) -> dict:
    exercise: dict = {
        "burden_band": burden_band,
        "analysis": {
            "saved": True,
            "combined_fraction": fraction,
        },
    }
    if s is not None:
        exercise["s"] = s
    if t is not None:
        exercise["t"] = t
    return exercise


def test_rst_window_for_step_walks_from_top_to_bottom():
    assert rst_window_for_step(0) == (RST_WINDOW_TOP - RST_WINDOW_WIDTH + 1, RST_WINDOW_TOP)
    assert rst_window_for_step(0) == (7, 9)
    assert rst_window_for_step(1) == (6, 8)
    assert rst_window_for_step(5) == (2, 4)
    assert rst_window_for_step(MAX_RST_STEP) == (2, 4)


def test_rst_window_for_step_clamps_out_of_range():
    assert rst_window_for_step(-1) == rst_window_for_step(0)
    assert rst_window_for_step(99) == rst_window_for_step(MAX_RST_STEP)


def test_is_eligible_only_when_drawn_equals_window_bottom():
    # Step 2 window is (5, 7); only s=5 is eligible.
    assert is_eligible_for_axis(5, 2) is True
    assert is_eligible_for_axis(6, 2) is False
    assert is_eligible_for_axis(7, 2) is False


def test_resolve_rst_advances_each_axis_independently_with_strong_streak():
    # Band 1: S met threshold, T did not — only S advances.
    evidence = {
        "bands": [
            {
                "burden_band": 1,
                "s_axis": {"strong_streak": 3, "low_streak": 0},
                "t_axis": {"strong_streak": 2, "low_streak": 0},
            },
        ],
    }
    resolved = resolve_rst_steps(evidence, current_steps={1: (0, 0)})
    assert resolved == {1: (1, 0)}


def test_resolve_rst_drops_with_low_streak():
    evidence = {
        "bands": [
            {
                "burden_band": 1,
                "s_axis": {"strong_streak": 0, "low_streak": 2},
                "t_axis": {"strong_streak": 0, "low_streak": 1},
            },
        ],
    }
    resolved = resolve_rst_steps(evidence, current_steps={1: (3, 2)})
    # S meets drop threshold, T does not.
    assert resolved == {1: (2, 2)}


def test_resolve_rst_caps_at_max_step():
    evidence = {
        "bands": [
            {
                "burden_band": 1,
                "s_axis": {"strong_streak": 10, "low_streak": 0},
                "t_axis": {"strong_streak": 10, "low_streak": 0},
            },
        ],
    }
    resolved = resolve_rst_steps(evidence, current_steps={1: (MAX_RST_STEP, MAX_RST_STEP)})
    assert resolved == {1: (MAX_RST_STEP, MAX_RST_STEP)}


def test_resolve_rst_floors_at_zero():
    evidence = {
        "bands": [
            {
                "burden_band": 1,
                "s_axis": {"strong_streak": 0, "low_streak": 5},
                "t_axis": {"strong_streak": 0, "low_streak": 5},
            },
        ],
    }
    resolved = resolve_rst_steps(evidence, current_steps={1: (0, 0)})
    assert resolved == {1: (0, 0)}


def test_resolve_rst_preserves_bands_absent_from_evidence():
    evidence = {
        "bands": [
            {
                "burden_band": 1,
                "s_axis": {"strong_streak": 3, "low_streak": 0},
                "t_axis": {"strong_streak": 3, "low_streak": 0},
            },
        ],
    }
    resolved = resolve_rst_steps(evidence, current_steps={1: (0, 0), 2: (2, 1)})
    assert resolved == {1: (1, 1), 2: (2, 1)}


def test_load_rst_axis_evidence_ignores_sessions_below_max_gear():
    # Band 1 at gear 2 — RST sub-axis is not engaged below MAX_GEAR.
    sessions = [
        _session(
            "2026-05-21T10:00:00Z",
            bands=[{"index": 1, "gear": 2}],
            rst_steps=[{"index": 1, "s_step": 0, "t_step": 0}],
            exercises=[_ex(1, 1.0, s=7, t=7)],
        ),
    ]
    evidence = load_rst_axis_evidence(sessions, claimed_set_key="K M U")
    assert evidence["bands"] == []


def test_load_rst_axis_evidence_only_counts_eligible_draws():
    # Two gear-3 sessions at step 0 (window 7..9, bottom = 7).
    # First exercise: s=7 (eligible), t=9 (not eligible).
    # Second exercise: s=8 (not eligible), t=7 (eligible).
    sessions = [
        _session(
            "2026-05-21T11:00:00Z",
            bands=[{"index": 1, "gear": 3}],
            rst_steps=[{"index": 1, "s_step": 0, "t_step": 0}],
            exercises=[_ex(1, 0.97, s=7, t=9)],
        ),
        _session(
            "2026-05-21T10:00:00Z",
            bands=[{"index": 1, "gear": 3}],
            rst_steps=[{"index": 1, "s_step": 0, "t_step": 0}],
            exercises=[_ex(1, 0.96, s=8, t=7)],
        ),
    ]
    evidence = load_rst_axis_evidence(sessions, claimed_set_key="K M U")
    band = evidence["bands"][0]
    # S axis got the s=7 draw (fraction 0.97); T axis got the t=7 draw (0.96).
    assert band["s_axis"]["recent_fractions"] == [0.97]
    assert band["t_axis"]["recent_fractions"] == [0.96]


def test_load_rst_axis_evidence_skips_pre_schema_sessions():
    # No rst_steps in generation, no per-exercise s/t — pre-2.1 record.
    sessions = [
        _session(
            "2026-05-21T10:00:00Z",
            bands=[{"index": 1, "gear": 3}],
            rst_steps=None,
            exercises=[_ex(1, 1.0, s=None, t=None)],
        ),
    ]
    evidence = load_rst_axis_evidence(sessions, claimed_set_key="K M U")
    assert evidence["bands"] == []


def test_load_rst_axis_evidence_streaks_count_at_current_step():
    # Three strong eligible S-axis sessions, all at step 0 → streak = 3.
    sessions = [
        _session(
            f"2026-05-21T1{i}:00:00Z",
            bands=[{"index": 1, "gear": 3}],
            rst_steps=[{"index": 1, "s_step": 0, "t_step": 0}],
            exercises=[_ex(1, 1.0, s=7, t=7)],
        )
        for i in range(3, 0, -1)  # newest first when sorted
    ]
    evidence = load_rst_axis_evidence(sessions, claimed_set_key="K M U")
    band = evidence["bands"][0]
    assert band["s_axis"]["strong_streak"] == 3
    assert band["t_axis"]["strong_streak"] == 3


def test_load_rst_axis_evidence_step_change_breaks_streak():
    # Newest session at step 1 (eligible: s=6), older at step 0 (eligible: s=7).
    # The streak should only count the newest entry because step changed.
    sessions = [
        _session(
            "2026-05-21T12:00:00Z",
            bands=[{"index": 1, "gear": 3}],
            rst_steps=[{"index": 1, "s_step": 1, "t_step": 0}],
            exercises=[_ex(1, 1.0, s=6, t=7)],
        ),
        _session(
            "2026-05-21T11:00:00Z",
            bands=[{"index": 1, "gear": 3}],
            rst_steps=[{"index": 1, "s_step": 0, "t_step": 0}],
            exercises=[_ex(1, 1.0, s=7, t=7)],
        ),
    ]
    evidence = load_rst_axis_evidence(sessions, claimed_set_key="K M U")
    band = evidence["bands"][0]
    assert band["s_axis"]["strong_streak"] == 1


def test_load_rst_axis_evidence_window_caps_entries_per_axis():
    sessions = [
        _session(
            f"2026-05-21T{i:02d}:00:00Z",
            bands=[{"index": 1, "gear": 3}],
            rst_steps=[{"index": 1, "s_step": 0, "t_step": 0}],
            exercises=[_ex(1, 1.0, s=7, t=7)],
        )
        for i in range(10, 0, -1)
    ]
    evidence = load_rst_axis_evidence(sessions, claimed_set_key="K M U", window_size=4)
    band = evidence["bands"][0]
    assert len(band["s_axis"]["recent_fractions"]) == 4


def test_latest_rst_steps_reads_most_recent_session():
    sessions = [
        _session(
            "2026-05-21T11:00:00Z",
            rst_steps=[{"index": 1, "s_step": 2, "t_step": 1}],
        ),
        _session(
            "2026-05-21T10:00:00Z",
            rst_steps=[{"index": 1, "s_step": 0, "t_step": 0}],
        ),
    ]
    assert latest_rst_steps_for_claimed_set(sessions, claimed_set_key="K M U") == {1: (2, 1)}


def test_latest_rst_steps_returns_empty_when_no_block():
    sessions = [_session("2026-05-21T10:00:00Z", rst_steps=None)]
    assert latest_rst_steps_for_claimed_set(sessions, claimed_set_key="K M U") == {}


def test_build_generation_profile_emits_rst_steps_when_provided():
    from copy_653.sequence.exercise_analysis import build_generation_profile

    profile = build_generation_profile(
        claimed_set=("K", "M"),
        candidate_count=20,
        exercise_count=2,
        gears=[3, 3],
        rst_steps={1: (0, 1), 2: (2, 3)},
    )
    assert profile["rst_steps"] == [
        {"index": 1, "s_step": 0, "t_step": 1},
        {"index": 2, "s_step": 2, "t_step": 3},
    ]


def test_build_generation_profile_omits_rst_steps_when_none():
    from copy_653.sequence.exercise_analysis import build_generation_profile

    profile = build_generation_profile(
        claimed_set=("K", "M"),
        candidate_count=20,
        exercise_count=2,
        gears=[0, 1],
    )
    assert "rst_steps" not in profile


def test_build_exercise_entries_emits_s_and_t_when_drawn():
    from copy_653.sequence.exercise_analysis import build_exercise_entries

    entries = build_exercise_entries(
        ["K M", "M K"],
        scores=[100, 110],
        gears=[3, 2],
        rst_draws=[(7, 3), (None, None)],
    )
    assert entries[0]["s"] == 7 and entries[0]["t"] == 3
    assert "s" not in entries[1] and "t" not in entries[1]
