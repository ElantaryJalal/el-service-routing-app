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
import re
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
    "per row — do not skip, merge, or invent rows. Adjacent rows can look "
    "almost identical (same Ort, same Bemerkung); they are distinct stops, "
    "return each printed row separately. The stop fields are named after the "
    "printed column headers — fill each field from its own column only: "
    "datum (as ISO YYYY-MM-DD), tag, kunde, auftrag (Auftrag/VST), ort, "
    "strasse (Straße: street name and number), plz (5-digit postal code), "
    "bemerkung. bemerkung is the verbatim contents of that row's Bemerkung "
    "cell — the RIGHTMOST column, after the PLZ — copied exactly as printed; "
    "rows differ, so transcribe each cell on its own and use null when the "
    "cell is blank. service_minutes is the on-site time in minutes if noted, "
    "else null. Use null for any value that is not present. The page header "
    "usually states tour-level fields: Kunde (customer), KW (calendar week), "
    "Zeitraum (date_from/date_to), Teamleiter, Mitarbeiter, Team-Nr. (team_no), "
    "Fahrzeug. Ignore internal codes such as Gewerke, VFL and VDP — they belong "
    "to no field and must not leak into team_lead, employee or any other value. "
    "Fix "
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

    # Field names mirror the printed German column headers (Datum, Tag,
    # Kunde, Auftrag/VST, Ort, Straße, PLZ, Bemerkung). With English names
    # the model cross-wired columns — e.g. the Ort value landed in both
    # ``street`` and ``city``; header-identical names anchor each field.
    datum: str | None
    tag: str | None
    kunde: str | None
    auftrag: str | None
    ort: str | None
    strasse: str | None
    plz: str | None
    # Verbatim Bemerkung cell. Asking the model to *classify* the cell into
    # tasks vs. remarks failed: a 3B model pattern-completes the dominant
    # task list onto every row (and dropped free-text remarks entirely).
    # Transcription it does reliably; ``_split_remark_cell`` does the split.
    bemerkung: str | None
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
    team_no: str | None
    vehicle: str | None
    stops: list[_WireStop] = Field(default_factory=list)


# A task code as printed on the plans: uppercase (umlauts/ß allowed after the
# first letter), digits, hyphens, spaces — e.g. EKW-B, KÖRBE SAMMELSTATION.
# Free text ("Nachbessern", "Austausch 15 Werbeabdeckungen …") contains
# lowercase letters and fails this, landing in remarks instead.
_TASK_CODE = re.compile(r"^[A-ZÄÖÜ][A-ZÄÖÜß0-9 \-]{0,30}$")


def _split_remark_cell(cell: str | None) -> tuple[list[str], str | None]:
    """Split a verbatim Bemerkung cell into (tasks, remarks).

    Cells hold either a slash-separated list of task codes
    ("EKW / EKW-B / KÖRBE / …") or free text. Task lists are printed in
    capitals, so the cell must be mostly uppercase; the per-segment check is
    then case-insensitive because the model re-cases codes ("Körbe" for
    KÖRBE). Free text — even slash-separated like "Zufahrt über Hof /
    Schlüssel beim Marktleiter" — stays a remark via its lowercase share.
    """
    if cell is None or not cell.strip():
        return [], None
    letters = [char for char in cell if char.isalpha()]
    upper_ratio = (
        sum(char.isupper() for char in letters) / len(letters) if letters else 0.0
    )
    parts = [part.strip() for part in cell.split("/") if part.strip()]
    if (
        parts
        and upper_ratio >= 0.7
        and all(_TASK_CODE.match(part.upper()) for part in parts)
    ):
        return parts, None
    return [], cell.strip()


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
    stops = []
    for stop in wire.stops:
        tasks, remarks = _split_remark_cell(stop.bemerkung)
        stops.append(
            ExtractedStop(
                date=stop.datum,
                weekday=stop.tag,
                customer=stop.kunde,
                order_no=stop.auftrag,
                street=stop.strasse,
                postal_code=stop.plz,
                city=stop.ort,
                tasks=tasks,
                remarks=remarks,
                service_minutes=stop.service_minutes,
            )
        )
    return ExtractedTour(**wire.model_dump(exclude={"stops"}), stops=stops)
