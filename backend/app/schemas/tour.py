from datetime import date

from pydantic import BaseModel, ConfigDict

from app.models.tour import DateMode


class TourRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer: str
    calendar_week: int
    date_from: date
    date_to: date
    status: str
    date_mode: DateMode


class TourUpdate(BaseModel):
    """Per-tour settings. Only provided fields are applied (PATCH)."""

    date_mode: DateMode | None = None
