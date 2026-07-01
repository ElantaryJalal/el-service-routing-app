from datetime import time

from pydantic import BaseModel, ConfigDict, Field

from app.models.stop import HoursSource


class StopUpdate(BaseModel):
    """Per-stop manual overrides. Only provided fields are applied (PATCH)."""

    opening_time: time | None = None
    closing_time: time | None = None
    service_minutes: int | None = Field(default=None, ge=30, le=600)


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


class StopDetail(StopRead):
    """A committed stop with the address, task labels, and coordinate the map
    needs. lat/lng come from the PostGIS geom (null until geocoded); tasks is
    the stop's task labels joined for display."""

    street: str | None
    postal_code: str | None
    city: str | None
    tasks: str | None
    lat: float | None
    lng: float | None


class CommitResult(BaseModel):
    tour_id: int
    status: str
    stops_total: int
    stops_enriched: int
