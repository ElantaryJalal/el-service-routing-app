"""Pre-commit (draft) tour schemas for the mobile ingestion flow.

A draft tour is produced by POST /tours/extract and edited on the Confirm
screen (GET /tours/{id}/draft, PATCH /tours/{id}/draft/stops/{id}) before the
user commits it. These mirror the provisional types in the mobile client
(mobile/src/api/client.ts): a stop's ``tasks`` is the comma-joined task labels
and ``confidence`` is the self-reported per-field extraction confidence used to
flag uncertain handwriting.
"""

from pydantic import BaseModel, Field


class DraftStop(BaseModel):
    id: int
    customer: str | None
    street: str | None
    postal_code: str | None
    city: str | None
    order_no: str | None
    tasks: str | None
    # Free-text instructions from the plan's remark column ("Nachbessern",
    # "Austausch 15 Werbeabdeckungen …") — a stop's work may be stated here
    # instead of task codes, so the Confirm screen must show it.
    remarks: str | None
    service_minutes: int | None
    # field name -> confidence in [0, 1]; absent = clearly printed.
    confidence: dict[str, float]


class TourDraft(BaseModel):
    tour_id: int
    stops: list[DraftStop]


class DraftStopUpdate(BaseModel):
    """PATCH body for a draft stop — only explicitly-set fields are applied.

    A field sent as ``null`` clears it; the endpoint distinguishes that from an
    omitted field via ``model_fields_set``.
    """

    customer: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    order_no: str | None = None
    tasks: str | None = None
    service_minutes: int | None = Field(default=None, ge=30, le=600)


class DraftStopCreate(BaseModel):
    """A manually added stop (the dispatcher's start-blank path). The stop is
    catalog-matched and geocoded exactly like an extracted row."""

    customer: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    order_no: str | None = None
    tasks: str | None = None
    service_minutes: int | None = Field(default=None, ge=30, le=600)
