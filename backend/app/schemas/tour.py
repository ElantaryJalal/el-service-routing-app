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
    """Per-tour settings and paper-plan header fields. Only provided fields are
    applied (PATCH); an explicit null clears an optional header field.

    The whole Tourenplan header is editable from the build screen: Kunde,
    Kalenderwoche and the Zeitraum, plus the office metadata (Teamleiter /
    Mitarbeiter / Team-Nr. / Fahrzeug). Unset fields are left untouched."""

    date_mode: DateMode | None = None
    customer: str | None = None
    calendar_week: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    team_lead: str | None = None
    employee: str | None = None
    team_no: str | None = None
    vehicle: str | None = None


class TourAssignRequest(BaseModel):
    user_id: int


class TourCreate(BaseModel):
    customer: str
    calendar_week: int
    date_from: date
    date_to: date
    # Paper-plan header (all optional): the dispatcher fills these at the top of
    # the tour-building screen exactly as on the printed Tourenplan.
    team_lead: str | None = None
    employee: str | None = None
    team_no: str | None = None
    vehicle: str | None = None
