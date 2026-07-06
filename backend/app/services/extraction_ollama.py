"""Vision extraction of a photographed tour plan via a local Ollama server.

Free and fully offline: a local vision model (default ``qwen2.5vl:3b``) reads
the photo with language context — "Zwickau", not "2wickau" — which Tesseract's
per-glyph matching cannot do on low-resolution scans. The trade-off is speed:
CPU-only inference takes minutes for a dense plan, acceptable for a weekly
task. Structured output is enforced with Ollama's JSON-schema ``format``.

The wire schema is a slimmed copy of ``ExtractedTour``: no per-field
confidence (a small local model can't self-report it meaningfully) and no
status hints. On a ~6 tok/s CPU decode, every field per row counts — the full
schema more than doubled generation time and overflowed the output budget.

Known 3B-model quirks (observed run-to-run, despite prompt instructions):
an occasional city-name typo, a remark drifting to the adjacent row, or a
foreign-chain store name normalized to the tour's main customer. Row count
and order, addresses, and postal codes read reliably; the Confirm screen and
catalog enrichment absorb the rest, and the anthropic provider remains the
quality path.
"""

from __future__ import annotations

import base64
from io import BytesIO

import httpx
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from app.config import settings
from app.services.extraction import ExtractedStop, ExtractedTour

# Longest image edge sent to the model. Prefill cost scales with pixel count,
# and a raw phone photo (~12 MP) took the CPU past the request timeout where
# a ~1 MP test image finished in minutes. 2048 px keeps a photographed A4
# plan's table text legible while capping the image-token budget.
_MAX_IMAGE_EDGE = 2048


def _prepare_image(image_bytes: bytes) -> bytes:
    """Normalize orientation (phone photos rotate via EXIF) and downscale."""
    image = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes)))
    image.thumbnail((_MAX_IMAGE_EDGE, _MAX_IMAGE_EDGE), Image.LANCZOS)
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


_PROMPT = (
    "You extract structured data from a photographed field-service tour plan "
    "for a cleaning company. The plan is a printed table, possibly with "
    "handwritten annotations, listing German supermarkets to service across a "
    "week. The page may contain more than one table section; read EVERY stop "
    "row of every section in top-to-bottom order and return one stops[] entry "
    "per row — do not skip, merge, or invent rows. Return ISO dates "
    "(YYYY-MM-DD). postal_code is the 5-digit German PLZ column. tasks is the "
    "list of task codes/labels for the stop (e.g. EKW, KÖRBE); when the "
    "remark column holds free text instead, put it in remarks, and keep "
    "remarks short. service_minutes is the on-site time in minutes if noted, "
    "else null. Use null for any value that is not present. The page header "
    "usually states tour-level fields: Kunde (customer), KW (calendar week), "
    "Zeitraum (date_from/date_to), Teamleiter, Mitarbeiter, Fahrzeug. Fix "
    "obvious OCR-style ambiguity using context (German city and street "
    "names), but copy each store/brand name exactly as printed — a row for a "
    "different chain (e.g. NETTO, LIDL) must keep that name, never be "
    "rewritten to the tour's main customer."
)


class _WireStop(BaseModel):
    """One stop row as the local model returns it (compact).

    Every field is required (nullable, but present): the JSON-schema grammar
    then *forces* the model to emit each key per row — a small model given
    optional fields lazily omits them and returns near-empty rows.
    """

    date: str | None
    weekday: str | None
    customer: str | None
    order_no: str | None
    street: str | None
    postal_code: str | None
    city: str | None
    tasks: list[str]
    remarks: str | None
    service_minutes: int | None


class _WireTour(BaseModel):
    """Tour header + stops. Required for the same reason as ``_WireStop``:
    given optional header fields the model omits them all and the tour comes
    back as "Unknown" with no dates, even when the plan header states them."""

    customer: str | None
    calendar_week: int | None
    date_from: str | None
    date_to: str | None
    team_lead: str | None
    employee: str | None
    vehicle: str | None
    stops: list[_WireStop] = Field(default_factory=list)


def extract_tour_ollama(image_bytes: bytes, media_type: str) -> ExtractedTour:
    """Extract a structured tour from a plan photo. Raises on API/parse failure."""
    payload = {
        "model": settings.ollama_model,
        "stream": False,
        "format": _WireTour.model_json_schema(),
        "options": {
            "temperature": 0,
            # A 26-row plan serializes to well over 2k tokens; don't truncate.
            "num_predict": 12000,
            # Ollama's 4096-token default context truncates mid-JSON on a
            # dense plan: image tokens + a 26-row payload need far more room.
            "num_ctx": 16384,
        },
        "messages": [
            {
                "role": "user",
                "content": _PROMPT,
                "images": [
                    base64.standard_b64encode(_prepare_image(image_bytes)).decode(
                        "ascii"
                    )
                ],
            }
        ],
    }
    response = httpx.post(
        f"{settings.ollama_url}/api/chat",
        json=payload,
        timeout=settings.ollama_timeout_seconds,
    )
    response.raise_for_status()
    content = response.json()["message"]["content"]
    wire = _WireTour.model_validate_json(content)
    return ExtractedTour(
        **wire.model_dump(exclude={"stops"}),
        stops=[ExtractedStop(**stop.model_dump()) for stop in wire.stops],
    )
