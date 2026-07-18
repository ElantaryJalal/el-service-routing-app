"""Scheduling helpers for the optimiser inputs."""

from __future__ import annotations

from datetime import time

from app.models.stop import Stop


def effective_window(
    stop: Stop,
    working_day_start: time,
    working_day_end: time,
) -> tuple[time, time]:
    """Return the usable [open, close] window for a stop.

    Hours live on the stop's linked store (read through effective_hours) and
    are clamped to the working window. If a bound is unknown it falls back to
    the working-window bound, so a stop with no known hours gets the full
    working window.
    """
    opening, closing = stop.effective_hours
    open_t = opening or working_day_start
    close_t = closing or working_day_end
    return (max(open_t, working_day_start), min(close_t, working_day_end))
