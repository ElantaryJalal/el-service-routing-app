from datetime import date, time

from pydantic import BaseModel


class PullCandidateRead(BaseModel):
    """A later-day stop the worker could pull into today, ranked by real drive
    time from their current position."""

    stop_id: int
    store_name: str
    drive_seconds: int
    drive_minutes: int
    projected_arrival: time
    service_minutes: int


class PullIntoTodayRequest(BaseModel):
    # The worker's "today". Defaults to the server date; passed explicitly so a
    # demo tour on other calendar days still works.
    day: date | None = None
