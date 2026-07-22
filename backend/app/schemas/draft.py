"""Pre-commit (draft) tour schemas for the mobile ingestion flow.

A draft tour is produced by POST /tours/extract and edited on the Confirm
screen (GET /tours/{id}/draft, PATCH /tours/{id}/draft/stops/{id}) before the
user commits it. These mirror the provisional types in the mobile client
(mobile/src/api/client.ts): a stop's ``tasks`` is the comma-joined task labels
and ``confidence`` is the self-reported per-field extraction confidence used to
flag uncertain handwriting.

The field order mirrors the office's paper Tourenplan (Datum, Tag, Kunde,
Auftrag/VST, Ort, Strasse, PLZ, Bemerkung), so the dispatcher's table reads
exactly like the document they fill today. ``weekday`` (Tag) is derived from
``date`` on write, never entered by hand.
"""

from datetime import date as Date

from pydantic import BaseModel, Field


class DraftStop(BaseModel):
    id: int
    # Datum / Tag — the plan row's date and its (auto-derived) weekday label.
    date: str | None
    weekday: str | None
    customer: str | None
    # Auftrag/VST — the office's order/job number for the row.
    order_no: str | None
    street: str | None
    postal_code: str | None
    city: str | None
    tasks: str | None
    # Free-text instructions from the plan's remark column ("Nachbessern",
    # "Austausch 15 Werbeabdeckungen …") — a stop's work may be stated here
    # instead of task codes, so the Confirm screen must show it.
    remarks: str | None
    service_minutes: int | None
    # The catalog store this row is linked to (set when picked via type-ahead
    # or matched on commit); null until then.
    store_id: int | None
    # field name -> confidence in [0, 1]; absent = clearly printed.
    confidence: dict[str, float]


class TourDraft(BaseModel):
    tour_id: int
    stops: list[DraftStop]


class DraftStopUpdate(BaseModel):
    """PATCH body for a draft stop — only explicitly-set fields are applied.

    A field sent as ``null`` clears it; the endpoint distinguishes that from an
    omitted field via ``model_fields_set``. Setting ``date`` re-derives the
    weekday (Tag); the weekday itself is never written directly.
    """

    date: Date | None = None
    customer: str | None = None
    order_no: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    tasks: str | None = None
    remarks: str | None = None
    service_minutes: int | None = Field(default=None, ge=30, le=600)


class DraftStopCreate(BaseModel):
    """A manually added stop (the dispatcher's start-blank path). The stop is
    catalog-matched and geocoded exactly like an extracted row — unless
    ``store_id`` is given (the dispatcher picked a known store via type-ahead),
    in which case it links that store directly: no re-typing, no re-geocoding.
    """

    date: Date | None = None
    customer: str | None = None
    order_no: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    tasks: str | None = None
    remarks: str | None = None
    service_minutes: int | None = Field(default=None, ge=30, le=600)
    # A type-ahead pick from the catalog: link this store verbatim.
    store_id: int | None = None
