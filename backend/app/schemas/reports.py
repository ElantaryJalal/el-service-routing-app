from datetime import date, datetime

from pydantic import BaseModel


class TourCounts(BaseModel):
    """Tours overlapping the reporting week, by lifecycle status."""

    total: int
    draft: int
    planned: int
    assigned: int
    in_progress: int
    done: int


class DayLoad(BaseModel):
    """One day of the week: stops planned for it vs. work completed on it."""

    day: date
    planned: int
    completed: int


class OnTimeStats(BaseModel):
    """Completion punctuality over stops that have both an ETA and a
    completion timestamp. on_time means completed_at <= eta + tolerance."""

    sample_count: int
    on_time_count: int
    # None while there are no samples (avoids a fake 0% / 100%).
    on_time_rate: float | None
    average_delta_minutes: float | None
    tolerance_minutes: int


class OutstandingStop(BaseModel):
    """A market still waiting to be serviced this week."""

    stop_id: int
    tour_id: int
    customer: str | None
    # The linked store's real name (source of truth); null when unmatched.
    # Prefer it over the printed customer claim for display.
    store_name: str | None = None
    city: str | None
    assigned_day: date | None
    eta: datetime | None


class OverviewReport(BaseModel):
    """The executive this-week snapshot: work planned vs. work completed."""

    date_from: date
    date_to: date
    tours: TourCounts
    stops_planned: int
    stops_completed: int
    days: list[DayLoad]
    on_time: OnTimeStats
    outstanding: list[OutstandingStop]
