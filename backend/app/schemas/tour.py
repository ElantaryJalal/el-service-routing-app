from datetime import date

from pydantic import BaseModel, ConfigDict

from app.models.tour import DateMode, TourStatus


class TourRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer: str
    calendar_week: int
    date_from: date
    date_to: date
    status: TourStatus
    date_mode: DateMode
    assigned_user_id: int | None
    # Office metadata printed on the paper plan — display only, no logic.
    team_lead: str | None = None
    employee: str | None = None
    team_no: str | None = None
    vehicle: str | None = None


class TourUpdate(BaseModel):
    """Per-tour settings. Only provided fields are applied (PATCH)."""

    date_mode: DateMode | None = None


class TourAssignRequest(BaseModel):
    user_id: int


class TourCreate(BaseModel):
    customer: str
    calendar_week: int
    date_from: date
    date_to: date
