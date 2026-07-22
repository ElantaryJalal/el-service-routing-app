from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel

from app.models.store import (
    AddressProvenance,
    GeomProvenance,
    HoursSource,
    StoreSize,
)


class StopSuggestion(BaseModel):
    """A type-ahead suggestion for the draft editor: a known place the typed
    text matches, with everything needed to fill the row in one click.
    Sourced from the store catalog and, for markets that never made it into
    the catalog, from stops on previous tours."""

    # The catalog store, when the match is a known store — the row links it
    # directly on pick (verified coordinate/hours/attributes), no re-typing.
    # Null for history-only suggestions (markets never added to the catalog).
    store_id: int | None
    name: str
    street: str | None
    postal_code: str | None
    city: str | None
    # Auftrag/VST the office has used for this store before (from history), so
    # picking by name also restores the order number without re-typing it.
    order_no: str | None
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
    crew's actual — the office watches the delta between them. Completed
    visits with a ledger entry also carry the service actually performed:
    its tasks, the responsible team, and the derived duration."""

    stop_id: int
    tour_id: int
    calendar_week: int
    date: date | None
    employee: str | None
    service_minutes: int | None
    eta: datetime | None
    completed_at: datetime | None
    # From the service ledger (null until a recompute derived this visit).
    tasks: str | None = None
    duration_minutes: int | None = None


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
    # The VERIFIED address — the source of truth stops read through; the
    # provenance below says how much it has actually been checked.
    street: str | None
    postal_code: str | None
    city: str | None
    lat: float | None
    lng: float | None
    address_provenance: AddressProvenance
    geom_provenance: GeomProvenance | None
    verified_at: datetime | None
    verified_by: str | None
    # Store opening hours (moved off the plan rows — a property of the shop).
    opening_time: time | None
    closing_time: time | None
    hours_source: HoursSource | None
    default_tasks: list[str] | None
    default_service_minutes: int | None
    # Learned from completion history (P4); null until enough samples exist.
    learned_service_minutes: int | None
    service_time_samples: int
    service_times_updated_at: datetime | None
    # Learned per service profile; the store-wide value above is the fallback.
    service_times: list[ServiceProfileTimeRead]
    # Total recorded time spent at this store, across the whole ledger.
    total_service_minutes: int
    services_recorded: int
    size: StoreSize | None
    in_mall: bool | None
    has_parking: bool | None
    attributes_updated_at: datetime | None
    attributes_updated_by: str | None
    # True once size, in_mall, and has_parking are all captured.
    attributes_complete: bool
