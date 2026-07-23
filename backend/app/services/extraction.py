"""Vision extraction of a photographed tour plan via the Anthropic Messages API.

Sends the photo to a vision-capable Claude model (``settings.extraction_model``,
default ``claude-sonnet-5``) and parses a structured tour + stops payload,
including a self-reported per-field confidence the Confirm screen uses to flag
uncertain handwriting.
"""

from __future__ import annotations

import base64

import anthropic
from pydantic import BaseModel, Field

from app.config import settings

_SUPPORTED_MEDIA = {"image/jpeg", "image/png", "image/webp", "image/gif"}


class StopConfidence(BaseModel):
    """Per-field extraction confidence in [0, 1]; omit when clearly printed."""

    street: float | None = None
    postal_code: float | None = None
    city: float | None = None
    order_no: float | None = None
    tasks: float | None = None
    service_minutes: float | None = None


class ExtractedStop(BaseModel):
    date: str | None = None
    weekday: str | None = None
    customer: str | None = None
    order_no: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    tasks: list[str] = Field(default_factory=list)
    remarks: str | None = None
    service_minutes: int | None = None
    status_hint: str | None = None
    confidence: StopConfidence = Field(default_factory=StopConfidence)


class ExtractedTour(BaseModel):
    customer: str | None = None
    calendar_week: int | None = None
    date_from: str | None = None
    date_to: str | None = None
    team_lead: str | None = None
    employee: str | None = None
    team_no: str | None = None
    vehicle: str | None = None
    stops: list[ExtractedStop] = Field(default_factory=list)


_SYSTEM = (
    "You extract structured data from a photographed field-service tour plan for "
    "a cleaning company. The plan is a printed table, often with handwritten "
    "annotations, listing German supermarkets to service across a week. Read "
    "every stop row in top-to-bottom order. Return ISO dates (YYYY-MM-DD) where a "
    "date is legible. service_minutes is the on-site time in minutes if noted, "
    "else null. tasks is the list of task codes/labels for the stop (e.g. EKW, "
    "Fussmatten). For each stop set confidence in [0, 1] per field: high (near "
    "1.0) for clearly printed text, low (below 0.6) for uncertain handwriting or "
    "partially obscured values; omit a field's confidence when it is clearly "
    "printed. Use null for any value that is not present. "
    "Read each row's customer (Kunde) INDEPENDENTLY — different rows may name "
    "different clients (e.g. one 'HIT Frische 111' row among 'ALDI NORD' rows); "
    "never copy one row's client onto the others or collapse them to a default. "
    "order_no is the row's Auftrag/VST number, transcribed verbatim. remarks "
    "(Bemerkung) is the row's full free-text note — transcribe it COMPLETELY, "
    "never truncated or summarized. From the header capture team_lead "
    "(Teamleiter), employee (Mitarbeiter), team_no (Team-Nr.) and vehicle "
    "(Fahrzeug) as separate values; ignore internal codes such as Gewerke, VFL "
    "and VDP entirely — they are not part of any field."
)

_PROMPT = (
    "Extract the tour header and every stop row from this tour plan, preserving "
    "the row order."
)


def normalize_media_type(content_type: str | None, filename: str | None) -> str:
    """Map an upload's content-type/filename to a Claude-supported image type."""
    if content_type in _SUPPORTED_MEDIA:
        return content_type
    name = (filename or "").lower()
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    if name.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def extract_tour(image_bytes: bytes, media_type: str) -> ExtractedTour:
    """Extract a structured tour from a plan photo. Raises on API/parse failure."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    data = base64.standard_b64encode(image_bytes).decode("ascii")
    response = client.messages.parse(
        model=settings.extraction_model,
        max_tokens=8000,
        system=_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": data,
                        },
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
        output_format=ExtractedTour,
    )
    parsed = response.parsed_output
    if parsed is None:
        raise ValueError("model returned no parseable tour")
    return parsed
