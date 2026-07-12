from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field

from app.models.stop import HoursSource


class StopUpdate(BaseModel):
    """Per-stop manual overrides. Only provided fields are applied (PATCH)."""

    opening_time: time | None = None
    closing_time: time | None = None
    service_minutes: int | None = Field(default=None, ge=30, le=600)


class StopCompleteRequest(BaseModel):
    """Body for POST /stops/{id}/complete. force re-stamps completed_at even
    when the stop was already completed (normally a repeat call is a no-op)."""

    force: bool = False


class StopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tour_id: int
    customer: str | None
    opening_time: time | None
    closing_time: time | None
    service_minutes: int | None
    hours_source: HoursSource
    status: str
    completed_at: datetime | None


class StopDetail(StopRead):
    """A committed stop with the address, task labels, and coordinate the map
    needs. lat/lng come from the PostGIS geom (null until geocoded); tasks is
    the stop's task labels joined for display."""

    street: str | None
    postal_code: str | None
    city: str | None
    tasks: str | None
    # Free-text instructions from the plan's remark column; the work for a
    # stop may be stated here instead of task codes.
    remarks: str | None
    lat: float | None
    lng: float | None


class CommitResult(BaseModel):
    tour_id: int
    status: str
    stops_total: int
    stops_enriched: int
