"""On-device tour-plan extraction via Tesseract OCR — no external API.

Header-driven column parsing: OCR the photo to positioned words
(``image_to_data``), find the table's header row by fuzzy-matching its column
labels (Markt, Straße, PLZ, Ort, Aufgaben, …), infer column x-boundaries from
the label positions, then read **every** data row into those columns. Rows are
never dropped because their store is unknown — the catalog is an enrichment
layer (applied later by the endpoint), not a filter, so the plan's layout and
row set can be arbitrary.

Fallback when no header row is recognized: every line carrying a 5-digit
postal code becomes a stop — resolved against the catalog when possible, kept
as a raw best-effort read otherwise.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

import pytesseract
from PIL import Image
from sqlalchemy.orm import Session

from app.config import settings
from app.services.extraction import ExtractedStop, ExtractedTour, StopConfidence
from app.services.store_catalog import match_store_in_text

_PLZ = re.compile(r"\b(\d{5})\b")
_SHORT_NUM = re.compile(r"\b(\d{1,3})\b")
_KW = re.compile(r"\bKW\s*(\d{1,2})\b", re.IGNORECASE)
_DATE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
_EMPLOYEE = re.compile(r"Mitarbeiter[:\s]+([A-Za-zÄÖÜäöüß.\- ]{2,40})", re.IGNORECASE)

_SERVICE_MIN, _SERVICE_MAX = 30, 600

# Words below this Tesseract confidence flag their field for the Confirm
# screen (mirrors the vision provider's self-reported per-field confidence).
_CONFIDENCE_FLAG_BELOW = 0.85

# Recognized header labels -> ExtractedStop field. Matched fuzzily, so OCR
# typos ("Strafse") and label variants across plan layouts both resolve.
_HEADER_LABELS: dict[str, str] = {
    "datum": "date",
    "tag": "weekday",
    "markt": "customer",
    "kunde": "customer",
    "filiale": "customer",
    "objekt": "customer",
    "auftrag": "order_no",
    "auftrags": "order_no",
    "nr": "order_no",
    "auftragsnr": "order_no",
    "auftragsnummer": "order_no",
    "strasse": "street",
    "straße": "street",
    "adresse": "street",
    "anschrift": "street",
    "plz": "postal_code",
    "ort": "city",
    "stadt": "city",
    "aufgaben": "tasks",
    "aufgabe": "tasks",
    "taetigkeit": "tasks",
    "tätigkeit": "tasks",
    "leistung": "tasks",
    "leistungen": "tasks",
    "min": "service_minutes",
    "minuten": "service_minutes",
    "zeit": "service_minutes",
    "dauer": "service_minutes",
    "bemerkung": "remarks",
    "bemerkungen": "remarks",
    "hinweis": "remarks",
    "notiz": "remarks",
}

# Fields whose extraction confidence the Confirm screen can flag.
_CONFIDENCE_FIELDS = set(StopConfidence.model_fields)


@dataclass
class Word:
    """One OCR'd word with its box; the unit the column parser works on."""

    text: str
    left: int
    top: int
    width: int
    height: int
    conf: float  # Tesseract 0–100; -1 when unavailable

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2


def _parse_tsv(data: dict) -> list[Word]:
    words: list[Word] = []
    for i, text in enumerate(data["text"]):
        text = text.strip()
        # Table borders/rules OCR as bare punctuation ("|", "—"); they carry
        # no content and would only pollute the cell they fall into.
        if not text or not re.search(r"[0-9A-Za-zÄÖÜäöüß]", text):
            continue
        words.append(
            Word(
                text=text,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
                conf=float(data["conf"][i]),
            )
        )
    return words


def _ocr_words(image_bytes: bytes, languages: str) -> list[Word]:
    """OCR the image to positioned words. Isolated so tests can stub it."""
    image = Image.open(io.BytesIO(image_bytes))
    data = pytesseract.image_to_data(
        image, lang=languages, output_type=pytesseract.Output.DICT
    )
    return _parse_tsv(data)


def _ocr_words_sparse(image_bytes: bytes, languages: str) -> list[Word]:
    """Second OCR pass in sparse-text mode (``--psm 11``).

    The default page segmentation sometimes swallows a header label whole
    (observed: "Aufgaben" missing while every neighbour read fine); sparse
    mode recovers such words. Only used to fill gaps in the header row.
    Isolated so tests can stub it.
    """
    image = Image.open(io.BytesIO(image_bytes))
    data = pytesseract.image_to_data(
        image, lang=languages, config="--psm 11", output_type=pytesseract.Output.DICT
    )
    return _parse_tsv(data)


def _rows(words: list[Word]) -> list[list[Word]]:
    """Cluster words into visual rows by vertical position.

    Tesseract often segments table columns into separate blocks, so its own
    line numbering can split one visual row — cluster on y instead.
    """
    if not words:
        return []
    heights = sorted(w.height for w in words)
    tolerance = max(6.0, heights[len(heights) // 2] * 0.7)

    rows: list[list[Word]] = []
    current: list[Word] = []
    current_y = 0.0
    for word in sorted(words, key=lambda w: w.center_y):
        if current and word.center_y - current_y > tolerance:
            rows.append(sorted(current, key=lambda w: w.left))
            current = []
        if not current:
            current_y = word.center_y
        current.append(word)
    rows.append(sorted(current, key=lambda w: w.left))
    return rows


def _match_label(word: str) -> str | None:
    """Map a header word to a stop field, tolerating OCR typos."""
    token = re.sub(r"[^a-zäöüß]", "", word.lower())
    if not token:
        return None
    if token in _HEADER_LABELS:
        return _HEADER_LABELS[token]
    best_field, best = None, 0.0
    for label, field in _HEADER_LABELS.items():
        ratio = SequenceMatcher(None, token, label).ratio()
        if ratio > best:
            best, best_field = ratio, field
    return best_field if best >= 0.8 else None


def _find_header(rows: list[list[Word]]) -> tuple[int, list[tuple[str, Word]]] | None:
    """The row whose words match the most distinct column labels (min 3)."""
    best: tuple[int, list[tuple[str, Word]]] | None = None
    for index, row in enumerate(rows):
        hits: list[tuple[str, Word]] = []
        seen: set[str] = set()
        for word in row:
            field = _match_label(word.text)
            if field and field not in seen:
                seen.add(field)
                hits.append((field, word))
        if len(hits) >= 3 and (best is None or len(hits) > len(best[1])):
            best = (index, hits)
    return best


def _augment_hits_sparse(
    hits: list[tuple[str, Word]],
    header_row: list[Word],
    sparse_words: list[Word],
) -> list[tuple[str, Word]]:
    """Add header labels the main pass missed but the sparse pass found.

    A candidate must sit on the header row's y-band, match a label for a
    field not yet hit, and not overlap an existing hit horizontally.
    """
    top = min(w.top for w in header_row)
    bottom = max(w.top + w.height for w in header_row)
    seen = {field for field, _ in hits}
    for word in sparse_words:
        if word.center_y < top or word.center_y > bottom:
            continue
        field = _match_label(word.text)
        if field is None or field in seen:
            continue
        if any(
            word.left < h.left + h.width and h.left < word.left + word.width
            for _, h in hits
        ):
            continue
        seen.add(field)
        hits.append((field, word))
    return hits


def _column_starts(
    hits: list[tuple[str, Word]], data_rows: list[list[Word]], tolerance: float
) -> list[tuple[float, str]]:
    """Each column's left x-origin, refined against the data rows.

    Printed table cells are left-aligned, so data words pile up at each
    column's origin. A pile near a header label (labels can be indented or
    centered differently from their cells) pins the column start better than
    the label itself does.
    """
    lefts = sorted(w.left for row in data_rows for w in row)
    piles: list[list[int]] = []
    for x in lefts:
        if piles and x - piles[-1][-1] <= tolerance:
            piles[-1].append(x)
        else:
            piles.append([x])
    pile_starts = [min(pile) for pile in piles if len(pile) >= 2]

    starts: list[tuple[float, str]] = []
    for field, word in sorted(hits, key=lambda h: h[1].left):
        anchored = min(
            (s for s in pile_starts if abs(s - word.left) <= 3 * tolerance),
            key=lambda s: abs(s - word.left),
            default=None,
        )
        starts.append((min(word.left, anchored) if anchored else word.left, field))
    return starts


def _bucket_row(
    row: list[Word], starts: list[tuple[float, str]], tolerance: float
) -> dict[str, list[Word]]:
    """Assign each word to the rightmost column starting at or before it.

    Left-edge assignment suits left-aligned cells: a long word in a narrow
    column ("Grundreinigung" under "Aufgaben") spills far past the next
    column's start, but its own left edge stays put.
    """
    cells: dict[str, list[Word]] = {field: [] for _, field in starts}
    for word in row:
        target = starts[0][1]
        for start, field in starts:
            if word.left >= start - tolerance:
                target = field
            else:
                break
        cells[target].append(word)
    return cells


def _iso_date(parts: tuple[str, str, str]) -> str:
    day, month, year = parts
    return f"{year}-{month}-{day}"


def _find_service_minutes(text: str) -> int | None:
    # The service time is the rightmost number; a street number sits mid-row,
    # so taking the last in-range 1–3 digit token avoids it.
    numbers = _SHORT_NUM.findall(text)
    if not numbers:
        return None
    value = int(numbers[-1])
    return value if _SERVICE_MIN <= value <= _SERVICE_MAX else None


def _row_stop(cells: dict[str, list[Word]]) -> ExtractedStop | None:
    """Build a stop from a bucketed table row; None for noise/footer rows."""
    text = {f: " ".join(w.text for w in ws).strip() for f, ws in cells.items()}
    filled = [field for field, value in text.items() if value]
    if len(filled) < 2 or not (
        text.get("customer") or text.get("street") or text.get("postal_code")
    ):
        return None

    date_match = _DATE.search(text.get("date", ""))
    plz_match = _PLZ.search(text.get("postal_code", ""))
    minutes = _find_service_minutes(text.get("service_minutes", ""))
    tasks = [
        part.strip()
        for part in re.split(r"[,;/]", text.get("tasks", ""))
        if part.strip()
    ]

    # Flag fields whose worst word Tesseract read shakily, so the Confirm
    # screen highlights them just like the vision provider's flags.
    confidence = StopConfidence()
    for field, ws in cells.items():
        if field not in _CONFIDENCE_FIELDS or not ws:
            continue
        worst = min((w.conf for w in ws if w.conf >= 0), default=None)
        if worst is not None and worst / 100 < _CONFIDENCE_FLAG_BELOW:
            setattr(confidence, field, round(worst / 100, 2))

    return ExtractedStop(
        date=_iso_date(date_match.groups()) if date_match else None,
        weekday=text.get("weekday") or None,
        customer=text.get("customer") or None,
        order_no=text.get("order_no") or None,
        street=text.get("street") or None,
        postal_code=plz_match.group(1) if plz_match else None,
        city=text.get("city") or None,
        tasks=tasks,
        remarks=text.get("remarks") or None,
        service_minutes=minutes,
        confidence=confidence,
    )


def _fallback_stops(db: Session, rows: list[list[Word]]) -> list[ExtractedStop]:
    """No header found: every postal-code-bearing line becomes a stop.

    Catalog resolution identifies the row when it can; an unmatched row is
    kept as a raw read (never dropped) — the endpoint geocodes it and the
    Confirm screen is where the user tidies it up.
    """
    stops: list[ExtractedStop] = []
    for row in rows:
        line = " ".join(w.text for w in row)
        plz_tokens = _PLZ.findall(line)
        if not plz_tokens:
            continue  # meta/header/noise line — carries no address
        plz = plz_tokens[-1]  # order numbers precede the address on a row
        store = match_store_in_text(db, line, plz)
        if store is not None:
            stops.append(
                ExtractedStop(
                    customer=store.name,  # canonical -> endpoint re-matches
                    postal_code=plz,
                    city=store.city,
                    service_minutes=_find_service_minutes(line),
                )
            )
        else:
            cleaned = _PLZ.sub(" ", line)
            cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -|")
            stops.append(
                ExtractedStop(
                    customer=cleaned or None,
                    postal_code=plz,
                    service_minutes=_find_service_minutes(line),
                    remarks=line,
                )
            )
    return stops


def extract_tour_local(
    db: Session, image_bytes: bytes, media_type: str
) -> ExtractedTour:
    """Extract a tour from a plan photo using local OCR — any layout, all rows."""
    words = _ocr_words(image_bytes, settings.ocr_languages)
    rows = _rows(words)
    joined = "\n".join(" ".join(w.text for w in row) for row in rows)

    kw = _KW.search(joined)
    dates = _DATE.findall(joined)
    employee = _EMPLOYEE.search(joined)

    header = _find_header(rows)
    if header is not None:
        header_index, hits = header
        heights = sorted(w.height for w in words)
        tolerance = max(6.0, heights[len(heights) // 2] * 0.8)
        hits = _augment_hits_sparse(
            hits,
            rows[header_index],
            _ocr_words_sparse(image_bytes, settings.ocr_languages),
        )
        data_rows = rows[header_index + 1 :]
        starts = _column_starts(hits, data_rows, tolerance)
        stops = [
            stop
            for row in data_rows
            if (stop := _row_stop(_bucket_row(row, starts, tolerance))) is not None
        ]
    else:
        stops = _fallback_stops(db, rows)

    return ExtractedTour(
        customer=None,
        calendar_week=int(kw.group(1)) if kw else None,
        date_from=_iso_date(dates[0]) if dates else None,
        date_to=_iso_date(dates[1]) if len(dates) > 1 else None,
        employee=employee.group(1).strip() if employee else None,
        stops=stops,
    )
