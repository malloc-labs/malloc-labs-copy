"""Shared helpers for WebSocket connection controllers."""

from __future__ import annotations

import asyncio
from typing import Any


async def supersede(task: asyncio.Task[Any] | None) -> None:
    """Cancel and await an in-flight per-slot task; swallow cancellation."""
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
