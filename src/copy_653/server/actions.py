"""Compatibility façade for legacy server action imports.

Action implementations live in focused modules. This module keeps the
historical private import paths stable while callers migrate to the
domain modules.
"""

from __future__ import annotations

from copy_653.server.claimed_symbols_actions import (
    _broadcast_claimed_state,
    _claim_symbol_action,
    _unclaim_symbol_action,
)
from copy_653.server.koch_actions import (
    _apply_koch_listening_probe_metadata,
    _build_warmup_exercises,
    _koch_challenge_rst_draws,
    _run_koch_session,
    _save_koch_answers_action,
    _start_action,
    _start_warmup_action,
)
from copy_653.server.recognition_answer_actions import (
    _coerce_voice_capture,
    _save_recognition_answers_action,
)
from copy_653.server.send_actions import (
    _play_copy_key_exercise,
    _request_copy_exercises_action,
    _request_copy_key_exercises_action,
)

__all__ = [
    "_apply_koch_listening_probe_metadata",
    "_broadcast_claimed_state",
    "_build_warmup_exercises",
    "_claim_symbol_action",
    "_coerce_voice_capture",
    "_koch_challenge_rst_draws",
    "_play_copy_key_exercise",
    "_request_copy_exercises_action",
    "_request_copy_key_exercises_action",
    "_run_koch_session",
    "_save_koch_answers_action",
    "_save_recognition_answers_action",
    "_start_action",
    "_start_warmup_action",
    "_unclaim_symbol_action",
]
