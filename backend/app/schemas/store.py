from datetime import datetime

from pydantic import BaseModel

from app.models.store import StoreSize


class StoreAttributesUpdate(BaseModel):
    """Crowdsourced attribute capture. Only provided fields are applied
    (PATCH); an explicit null clears an attribute back to "not captured"."""

    size: StoreSize | None = None
    in_mall: bool | None = None
    has_parking: bool | None = None
    # Who captured the attributes (free-text employee name; no auth yet).
    updated_by: str | None = None


class StoreRead(BaseModel):
    id: int
    name: str
    street: str | None
    postal_code: str | None
    city: str | None
    lat: float | None
    lng: float | None
    default_tasks: list[str] | None
    default_service_minutes: int | None
    size: StoreSize | None
    in_mall: bool | None
    has_parking: bool | None
    attributes_updated_at: datetime | None
    attributes_updated_by: str | None
    # True once size, in_mall, and has_parking are all captured.
    attributes_complete: bool
