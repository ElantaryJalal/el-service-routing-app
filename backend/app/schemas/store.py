from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.models.store import StoreSize


class StopSuggestion(BaseModel):
    """A type-ahead suggestion for the draft editor: a known place the typed
    text matches, with everything needed to fill the row in one click.
    Sourced from the store catalog and, for markets that never made it into
    the catalog, from stops on previous tours."""

    name: str
    street: str | None
    postal_code: str | None
    city: str | None
    service_minutes: int | None
    tasks: str | None
    source: Literal["catalog", "history"]


class StoreAttributesUpdate(BaseModel):
    """Crowdsourced attribute capture. Only provided fields are applied
    (PATCH); an explicit null clears an attribute back to "not captured"."""

    size: StoreSize | None = None
    in_mall: bool | None = None
    has_parking: bool | None = None
    # Who captured the attributes (free-text employee name; no auth yet).
    updated_by: str | None = None


class StoreVisit(BaseModel):
    """One (planned or completed) stop at this store, for the office view's
    visit-history table. eta is the optimiser's prediction, completed_at the
    crew's actual — the office watches the delta between them."""

    stop_id: int
    tour_id: int
    calendar_week: int
    date: date | None
    employee: str | None
    service_minutes: int | None
    eta: datetime | None
    completed_at: datetime | None


class ServiceProfileTimeRead(BaseModel):
    """Learned duration for one service profile (task set) at a store —
    the same market takes a different time depending on which tasks (which
    team) the visit is for."""

    task_signature: str
    tasks_label: str | None
    samples: int
    learned_minutes: int | None


class StoreServiceTimeRead(BaseModel):
    """Per-store outcome of a service-time recompute run."""

    store_id: int
    name: str
    samples: int
    learned_service_minutes: int | None
    by_service: list[ServiceProfileTimeRead] = []


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
    # Learned from completion history (P4); null until enough samples exist.
    learned_service_minutes: int | None
    service_time_samples: int
    service_times_updated_at: datetime | None
    # Learned per service profile; the store-wide value above is the fallback.
    service_times: list[ServiceProfileTimeRead]
    size: StoreSize | None
    in_mall: bool | None
    has_parking: bool | None
    attributes_updated_at: datetime | None
    attributes_updated_by: str | None
    # True once size, in_mall, and has_parking are all captured.
    attributes_complete: bool
