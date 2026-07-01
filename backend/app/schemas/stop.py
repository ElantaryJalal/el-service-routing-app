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


class CommitResult(BaseModel):
    tour_id: int
    status: str
    stops_total: int
    stops_enriched: int
