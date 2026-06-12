"""Internal analysis for saved Koch Exercise attempts.

This module deliberately produces backend evidence, not learner-facing
feedback. The values it returns are intended for records, diagnostics,
and future exercise selection. They are not scores, grades, or progress
metrics for the listening surface.
"""

from __future__ import annotations

from copy_653.sequence.exercise_confusion import load_confusion_pairs as load_confusion_pairs
from copy_653.sequence.exercise_scoring import (
    ANALYSIS_VERSION as ANALYSIS_VERSION,
    FIXED_LISTENING_ANCHOR as FIXED_LISTENING_ANCHOR,
    _align as _align,
    _band_state as _band_state,
    _coerce_int as _coerce_int,
    _fraction as _fraction,
    _levenshtein as _levenshtein,
    _repeat_weight as _repeat_weight,
    _symbols_only as _symbols_only,
    analyse_answer as analyse_answer,
    burden_score_for_exercise as burden_score_for_exercise,
    normalize_exercise_text as normalize_exercise_text,
    spacing_weight_for_claimed_set as spacing_weight_for_claimed_set,
    strip_fixed_anchor as strip_fixed_anchor,
)
from copy_653.sequence.exercise_records import (
    GENERATION_PROFILE_VERSION as GENERATION_PROFILE_VERSION,
    apply_answers_to_entries as apply_answers_to_entries,
    build_exercise_entries as build_exercise_entries,
    build_generation_profile as build_generation_profile,
)
from copy_653.sequence.exercise_progression import (
    DEFAULT_EVIDENCE_WINDOW_SIZE as DEFAULT_EVIDENCE_WINDOW_SIZE,
    LOW_FRACTION as LOW_FRACTION,
    MAX_CONTENT_GEAR as MAX_CONTENT_GEAR,
    MAX_GEAR as MAX_GEAR,
    N_CLEAN_RUNS_FOR_SHIFT as N_CLEAN_RUNS_FOR_SHIFT,
    N_LOW_RUNS_FOR_SHIFT_DOWN as N_LOW_RUNS_FOR_SHIFT_DOWN,
    STRONG_FRACTION as STRONG_FRACTION,
    _exercise_gear as _exercise_gear,
    _gears_from_generation as _gears_from_generation,
    _matching_sessions as _matching_sessions,
    _streak_at_current_gear as _streak_at_current_gear,
    is_ready_for_next_symbol as is_ready_for_next_symbol,
    latest_gears_for_claimed_set as latest_gears_for_claimed_set,
    load_band_evidence as load_band_evidence,
    load_band_history as load_band_history,
    record_claimed_set_key as record_claimed_set_key,
    resolve_gears as resolve_gears,
)
from copy_653.sequence.exercise_rst import (
    MAX_RST_STEP as MAX_RST_STEP,
    N_LOW_RUNS_FOR_RST_STEP_DOWN as N_LOW_RUNS_FOR_RST_STEP_DOWN,
    RST_WINDOW_TOP as RST_WINDOW_TOP,
    RST_WINDOW_WIDTH as RST_WINDOW_WIDTH,
    _exercise_rst_draw as _exercise_rst_draw,
    _rst_steps_from_generation as _rst_steps_from_generation,
    _shift_step as _shift_step,
    _step_axis_streak as _step_axis_streak,
    is_eligible_for_axis as is_eligible_for_axis,
    latest_rst_steps_for_claimed_set as latest_rst_steps_for_claimed_set,
    load_rst_axis_evidence as load_rst_axis_evidence,
    resolve_rst_steps as resolve_rst_steps,
    rst_window_for_step as rst_window_for_step,
)
