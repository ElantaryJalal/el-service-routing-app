from datetime import date, time
from typing import Literal

from pydantic import BaseModel

from app.models.tour import DateMode


class OptimiseRequest(BaseModel):
    """Optional POST /tours/{id}/optimise body.

    scope='remaining' is the mid-week re-plan: completed stops stay where
    they are, everything still open (including stops stranded on earlier
    days) is redistributed over the days from from_date on. from_date
    defaults to today.
    """

    scope: Literal["week", "remaining"] = "week"
    from_date: date | None = None


class DayStop(BaseModel):
    stop_id: int
    sequence: int
    # Null after a manual move — only the solver can estimate an arrival.
    eta: time | None


class DaySummary(BaseModel):
    date: date
    stops: list[DayStop]
    drive_seconds: int
    service_seconds: int
    day_end: time | None
    near_limit: bool


class UnassignedStop(BaseModel):
    stop_id: int
    reason: str


class OptimiseResult(BaseModel):
    tour_id: int
    # The mode this schedule was computed under, so clients caching the result
    # can render the Date mode control without another request.
    date_mode: DateMode
    days: list[DaySummary]
    unassigned: list[UnassignedStop]
