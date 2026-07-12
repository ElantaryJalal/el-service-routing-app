from datetime import date, time

from pydantic import BaseModel

from app.models.tour import DateMode


class DayStop(BaseModel):
    stop_id: int
    sequence: int
    eta: time


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
