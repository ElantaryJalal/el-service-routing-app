from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.stop import StartSource
from app.models.store import AddressProvenance, HoursSource, StoreSize
from app.services.optimiser import ServiceEstimateSource


class StopUpdate(BaseModel):
    """Per-stop manual overrides. Only provided fields are applied (PATCH).

    opening/closing_time write through to the stop's linked *store* (hours are
    a property of the shop); a stop without a store cannot hold hours.
    """

    opening_time: time | None = None
    closing_time: time | None = None
    service_minutes: int | None = Field(default=None, ge=30, le=600)


class StopPlanUpdate(BaseModel):
    """Manual plan edit (PATCH /stops/{id}/plan): move the stop to a day —
    appended, or at the 1-based position — or take it off the plan entirely
    (assigned_day=null)."""

    assigned_day: date | None
    position: int | None = Field(default=None, ge=1)


class StopCompleteRequest(BaseModel):
    """Body for POST /stops/{id}/complete. force re-stamps completed_at even
    when the stop was already completed (normally a repeat call is a no-op)."""

    force: bool = False


class StopStartRequest(BaseModel):
    """Body for POST /stops/{id}/start. Idempotent: a repeat call (e.g. an
    offline-sync retry) keeps the original started_at unless force is set.
    source records how the start was triggered (defaults to a worker tap)."""

    force: bool = False
    source: StartSource = StartSource.manual


class ResolveAddressRequest(BaseModel):
    """Dispatcher's verdict on a plan-vs-store address mismatch.

    'keep_store' (the default expectation): the store's verified address
    stands; the claim stays as audit and the review row is dismissed durably.
    'use_claim': the plan was right — the store's address is updated from the
    claim and marked verified by the dispatcher.
    """

    action: Literal["keep_store", "use_claim"]


class StopRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    tour_id: int
    # Auftrag/VST — the office's order/job number for this row (their reference
    # and likely invoicing key). First-class plan data, shown alongside the
    # store; null when the plan printed none.
    order_no: str | None = None
    # The client named on the plan row (Kunde), a per-row fact never coerced to
    # a tour-wide default — e.g. "HIT Frische 111" on a row whose neighbours say
    # "ALDI NORD BEUCHA". Distinct from store_name (the physical location): a
    # row shows BOTH which client and which store.
    customer: str | None
    # The specific physical store serviced (from the catalog), e.g. "ALDI
    # Leipzig-Plagwitz"; null when the row was never matched to a catalog store.
    store_name: str | None = None
    # Hours are stored on the linked store; these read through the stop's
    # effective_* views (wire names kept stable for the clients).
    opening_time: time | None = Field(validation_alias="effective_opening_time")
    closing_time: time | None = Field(validation_alias="effective_closing_time")
    hours_source: HoursSource = Field(validation_alias="effective_hours_source")
    service_minutes: int | None
    status: str
    # When service began (POST /stops/{id}/start) and how it was triggered;
    # with completed_at this yields the direct service measurement.
    started_at: datetime | None = None
    start_source: StartSource = StartSource.none
    completed_at: datetime | None
    # Plan placement — set by the optimiser or a manual move (PATCH .../plan).
    assigned_day: date | None = None
    sequence: int | None = None
    # Predicted arrival from the stored plan; with completed_at this is the
    # actual-vs-predicted pair the dashboard reports on.
    eta: datetime | None = None
    unassigned_reason: str | None = None


class StopDetail(StopRead):
    """A committed stop with the address, task labels, and coordinate the map
    needs. street/postal_code/city and lat/lng are the *effective* values (the
    linked store's verified data when there is one); claimed_* is what the
    printed plan said — the audit trail shown when the paper was wrong."""

    street: str | None
    postal_code: str | None
    city: str | None
    claimed_street: str | None
    claimed_postal_code: str | None
    claimed_city: str | None
    # True when the plan's claimed address agrees with the store's verified
    # one; null = not checked (set during commit).
    address_matches_store: bool | None
    # Set once a dispatcher resolved the mismatch (survives re-commits).
    address_review_resolved_at: datetime | None
    address_review_resolved_by: str | None
    # The linked store's address trust level — 'printed'/'geocoded' stores are
    # new-store candidates the dispatcher should review before optimising.
    store_address_provenance: AddressProvenance | None
    tasks: str | None
    # pending | done | rework | skip | unknown. 'rework' is a Nachbessern
    # (fix-up) mission — shown alongside the task list, not instead of it.
    status_hint: str
    # Free-text instructions from the plan's remark column; the work for a
    # stop may be stated here instead of task codes.
    remarks: str | None
    lat: float | None
    lng: float | None
    # Best service-time estimate for THIS visit's task set, and where it came
    # from (per-task learned profile > store-wide > default). Always a number,
    # so the card never shows a bare "— min"; the source lets it label a plain
    # default honestly rather than pass it off as measured.
    service_estimate_minutes: int
    service_estimate_source: ServiceEstimateSource
    # Catalog store link (null when the stop wasn't matched). The completion
    # sheet shows the attribute-capture form only while
    # store_attributes_complete is False.
    store_id: int | None
    store_attributes_complete: bool | None
    # The linked store's crowdsourced attributes (null = not captured yet, so
    # the card shows a quick-capture control in place of the value).
    store_size: StoreSize | None
    store_in_mall: bool | None
    store_has_parking: bool | None
    # How many past visit-feedback notes exist for the store ("N past notes"
    # indicator on the stop card); 0 when the stop has no store.
    store_feedback_count: int


class MatchCandidateRead(BaseModel):
    store_id: int
    name: str
    score: float
    rule: str


class MatchReviewItem(BaseModel):
    """An ambiguous catalog match commit refused to auto-link — a false link
    silently sends the crew to the wrong store, so the dispatcher decides."""

    stop_id: int
    customer: str | None
    reason: str
    candidates: list[MatchCandidateRead]


class NewStoreRead(BaseModel):
    """A row that matched nothing became a candidate new store — an event
    worth noticing, not a silent insert."""

    stop_id: int
    store_id: int
    name: str


class AddressMismatchRead(BaseModel):
    """The plan printed an address that disagrees with the linked store's
    verified one. Both are kept: claimed_* is the audit trail that shows the
    office their plan was wrong."""

    stop_id: int
    store_id: int
    claimed: str
    verified: str


class CommitResult(BaseModel):
    tour_id: int
    status: str
    stops_total: int
    stops_enriched: int
    # Catalog resolution outcome: every stop linked to a store, how.
    stops_matched: int = 0
    new_stores: list[NewStoreRead] = []
    review_items: list[MatchReviewItem] = []
    address_mismatches: list[AddressMismatchRead] = []
    # Groups of stop ids that look like the same market twice (same catalog
    # store, or same normalized street+PLZ); the review UI prompts to resolve.
    duplicates: list[list[int]] = []
