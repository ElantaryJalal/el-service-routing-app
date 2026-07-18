from datetime import time
from types import SimpleNamespace

from app.services.scheduling import effective_window

WORK_START = time(8, 0)
WORK_END = time(18, 0)


def _stop(opening_time=None, closing_time=None):
    # effective_hours is the store read-through (hours live on the store).
    return SimpleNamespace(effective_hours=(opening_time, closing_time))


def test_unknown_hours_fall_back_to_working_window():
    assert effective_window(_stop(), WORK_START, WORK_END) == (WORK_START, WORK_END)


def test_store_hours_clamped_to_working_window():
    # Store open 07:00–20:00 is clamped to the 08:00–18:00 working day.
    stop = _stop(opening_time=time(7, 0), closing_time=time(20, 0))
    assert effective_window(stop, WORK_START, WORK_END) == (WORK_START, WORK_END)


def test_tighter_store_hours_win():
    stop = _stop(opening_time=time(9, 0), closing_time=time(16, 0))
    assert effective_window(stop, WORK_START, WORK_END) == (time(9, 0), time(16, 0))


def test_only_closing_known():
    # Only the feasibility-critical closing time is set.
    stop = _stop(closing_time=time(14, 0))
    assert effective_window(stop, WORK_START, WORK_END) == (WORK_START, time(14, 0))
