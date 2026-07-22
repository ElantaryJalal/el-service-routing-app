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
from functools import lru_cache

import pytesseract
from PIL import Image, ImageFilter, ImageOps
from sqlalchemy.orm import Session

from app.config import settings
from app.services.extraction import ExtractedStop, ExtractedTour, StopConfidence
from app.services.store_catalog import match_store_in_text

_PLZ = re.compile(r"\b(\d{5})\b")
_SHORT_NUM = re.compile(r"\b(\d{1,3})\b")
_KW = re.compile(r"\b(?:KW|Kalenderwoche)\s*(\d{1,2})\b", re.IGNORECASE)
_DATE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
_EMPLOYEE = re.compile(r"Mitarbeiter[:\s]+([A-Za-zÄÖÜäöüß.\- ]{2,40})", re.IGNORECASE)
_TEAM_LEAD = re.compile(
    r"Teamleiter(?:\s*\([A-Z]\))?[:\s]+([A-Za-zÄÖÜäöüß.\- ]{2,40})", re.IGNORECASE
)
_TEAM_NO = re.compile(r"Team[-\s]?Nr\.?[:\s]+([A-Za-z0-9\-]{1,20})", re.IGNORECASE)
_VEHICLE = re.compile(r"Fahrzeug[:\s]+([A-Za-z0-9ÄÖÜäöüß.\- ]{2,30})", re.IGNORECASE)
_TOUR_CUSTOMER = re.compile(
    r"Kunde[:\s]+([A-Za-z0-9ÄÖÜäöüß./\- ]{2,60})", re.IGNORECASE
)
# Adjacent header labels / internal codes that a greedy name capture swallows.
# A captured value is cut at the first of these so "Sophie Lehmann Gewerke VFL"
# becomes "Sophie Lehmann" and "a Team-Nr. SYS-R" becomes "a".
_HEADER_NOISE = re.compile(
    r"\b(?:Gewerke|VFL|VDP|Team[-\s]?Nr|Teamleiter|Mitarbeiter|Fahrzeug|Kunde|KW"
    r"|Kalenderwoche)\b",
    re.IGNORECASE,
)


def _clean_header_value(value: str | None) -> str | None:
    """Trim a header capture at the first adjacent label/internal code and drop
    surrounding punctuation. Returns None if nothing meaningful remains."""
    if value is None:
        return None
    cut = _HEADER_NOISE.split(value, maxsplit=1)[0]
    cleaned = re.sub(r"\s{2,}", " ", cut).strip(" .:-–")
    # A single stray character left after trimming is OCR noise, not a name.
    return cleaned if len(cleaned) >= 2 else None


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


def _deskew_angle(gray: Image.Image) -> float:
    """Estimate the page's small skew angle (degrees) via projection profiles.

    Text rows make the horizontal darkness profile spiky; the rotation that
    maximizes that spikiness (variance) is the deskew angle. Runs on a
    thumbnail, so it's cheap. Handles phone-photo skew of a few degrees, not
    sideways pages.
    """
    thumb = gray.copy()
    thumb.thumbnail((600, 600))
    best_angle, best_var = 0.0, -1.0
    for tenth in range(-30, 31, 5):  # -3.0° .. 3.0° in 0.5° steps
        angle = tenth / 10
        rotated = thumb.rotate(angle, fillcolor=255, resample=Image.BILINEAR)
        # Per-row mean brightness via a 1px-wide box resize.
        profile = list(rotated.resize((1, rotated.height), Image.BOX).getdata())
        mean = sum(profile) / len(profile)
        var = sum((v - mean) ** 2 for v in profile) / len(profile)
        if var > best_var:
            best_var, best_angle = var, angle
    return best_angle


def _preprocess(image_bytes: bytes) -> Image.Image:
    """Clean up a phone photo for Tesseract.

    Grayscale + autocontrast normalize dim/uneven lighting; deskew squares up
    the rows (column parsing clusters words by y, so skew smears rows into
    each other). Scaling is handled adaptively in ``_best_read``.
    """
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes)))
    image = image.convert("L")
    image = ImageOps.autocontrast(image, cutoff=1)
    angle = _deskew_angle(image)
    if abs(angle) >= 0.3:
        image = image.rotate(angle, expand=True, fillcolor=255, resample=Image.BICUBIC)
    return image


def _sharpen(image: Image.Image) -> Image.Image:
    return image.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))


def _quality(words: list[Word]) -> int:
    """How well a read went: count of confidently-recognized words."""
    return sum(1 for w in words if w.conf >= 60)


@lru_cache(maxsize=2)
def _best_read(image_bytes: bytes, languages: str) -> tuple[Image.Image, tuple]:
    """OCR at native size and 2×, keep the better read.

    A dense plan scanned/photographed small (~10px glyphs) needs the 2× pass;
    an adequately-sized image reads *worse* upscaled (interpolation smears
    crisp glyphs). Measuring instead of guessing handles both. Cached so the
    sparse header pass reuses the chosen geometry without re-deciding.
    """
    base = _preprocess(image_bytes)
    image = _sharpen(base)
    words = _tsv_words(image, languages)
    if base.width < 2400:
        scaled = _sharpen(base.resize((base.width * 2, base.height * 2), Image.LANCZOS))
        scaled_words = _tsv_words(scaled, languages)
        if _quality(scaled_words) > _quality(words):
            image, words = scaled, scaled_words
    return image, tuple(words)


def _tsv_words(image: Image.Image, languages: str, config: str = "") -> list[Word]:
    data = pytesseract.image_to_data(
        image, lang=languages, config=config, output_type=pytesseract.Output.DICT
    )
    return _parse_tsv(data)


def _ocr_words(image_bytes: bytes, languages: str) -> list[Word]:
    """OCR the image to positioned words. Isolated so tests can stub it."""
    return list(_best_read(image_bytes, languages)[1])


def _ocr_words_sparse(image_bytes: bytes, languages: str) -> list[Word]:
    """Second OCR pass in sparse-text mode (``--psm 11``).

    The default page segmentation sometimes swallows a header label whole
    (observed: "Aufgaben" missing while every neighbour read fine); sparse
    mode recovers such words. Only used to fill gaps in the header row.
    Isolated so tests can stub it. Runs on the image ``_best_read`` chose so
    both passes see identical geometry.
    """
    image, _ = _best_read(image_bytes, languages)
    return _tsv_words(image, languages, config="--psm 11")


def _rows(words: list[Word]) -> list[list[Word]]:
    """Cluster words into visual rows by vertical overlap.

    Tesseract often segments table columns into separate blocks, so its own
    line numbering can split one visual row. Center distance is too strict
    the other way: cells in one row sit on slightly different baselines
    (observed splitting real plan rows in half). A word belongs to a row when
    its y-extent overlaps the row's by half the word's height.
    """

    if not words:
        return []
    # Union-find on "same row": centers closer than 0.6× the pair's mean
    # glyph height. Pairwise (not greedy-envelope) so cells whose baselines
    # sit a little high or low still connect through their neighbours without
    # the cluster creeping into the next table row. Abnormally tall boxes
    # (OCR junk spanning two rows) would bridge rows, so they don't link —
    # they're attached to the nearest finished row afterwards.
    heights = sorted(w.height for w in words)
    median_height = heights[len(heights) // 2]
    linkable = [w for w in words if w.height <= 1.4 * median_height]
    outliers = [w for w in words if w.height > 1.4 * median_height]

    ordered = sorted(linkable, key=lambda w: w.center_y)
    parent = list(range(len(ordered)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    max_height = max((w.height for w in ordered), default=0)
    for i, first in enumerate(ordered):
        for j in range(i + 1, len(ordered)):
            second = ordered[j]
            gap = second.center_y - first.center_y
            if gap > 0.6 * (first.height + max_height) / 2:
                break
            if gap < 0.6 * (first.height + second.height) / 2:
                parent[find(i)] = find(j)

    clusters: dict[int, list[Word]] = {}
    for i, word in enumerate(ordered):
        clusters.setdefault(find(i), []).append(word)
    rows = sorted(clusters.values(), key=lambda ws: ws[len(ws) // 2].center_y)

    for word in outliers:
        target = min(
            rows,
            key=lambda ws: abs(ws[len(ws) // 2].center_y - word.center_y),
            default=None,
        )
        if target is not None:
            target.append(word)
        else:
            rows.append([word])
    return [sorted(ws, key=lambda w: w.left) for ws in rows]


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


def _is_header_row(row: list[Word]) -> bool:
    """True when a row reads as column labels rather than stop data."""
    fields = {f for w in row if (f := _match_label(w.text)) is not None}
    return len(fields) >= 3


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
    """Each column's left x-origin, aligned to the data rows' own piles.

    Printed table cells are left-aligned, so data words pile up at each
    column's origin — but header labels are often *centered* over their
    column, sitting well right of where the cells start. Trusting the labels
    directly shifts every cell into its left neighbour. Instead, align the
    label sequence to the pile sequence with an order-preserving minimum-cost
    matching; a label with no plausible pile (sparse column) keeps its own
    position.
    """
    hits = sorted(hits, key=lambda h: h[1].left)

    # Cluster data-word lefts into piles, tracking the whitespace gap before
    # each word: a real column start repeats across rows AND sits after a
    # sizeable gap; continuation words of multi-word cells ("NORD", "BEUCHA")
    # pile up too, but only one space-width behind their neighbour.
    entries: list[tuple[int, float]] = []  # (left, gap before word)
    for row in data_rows:
        prev_right: float | None = None
        for word in row:
            gap = float("inf") if prev_right is None else word.left - prev_right
            entries.append((word.left, gap))
            prev_right = word.left + word.width
    entries.sort()
    piles: list[list[tuple[int, float]]] = []
    for left, gap in entries:
        if piles and left - piles[-1][-1][0] <= tolerance:
            piles[-1].append((left, gap))
        else:
            piles.append([(left, gap)])
    min_support = max(2, len(data_rows) // 3)
    pile_starts: list[int] = []
    for pile in piles:
        if len(pile) < min_support:
            continue
        gaps = sorted(g for _, g in pile)
        if gaps[len(gaps) // 2] >= 2.5 * tolerance:  # median preceding gap
            pile_starts.append(min(left for left, _ in pile))

    # Monotone alignment: labels[i] -> pile or gap (keep label position).
    # A pile left of its label is cheap (headers are often centered over
    # left-aligned cells); right of it is suspect.
    gap_cost = 12 * tolerance
    n_labels, n_piles = len(hits), len(pile_starts)
    inf = float("inf")
    # cost[i][j]: labels[:i] placed considering piles[:j]
    cost = [[inf] * (n_piles + 1) for _ in range(n_labels + 1)]
    choice: dict[tuple[int, int], tuple[int, int, int | None]] = {}
    cost[0] = [0.0] * (n_piles + 1)
    for i in range(1, n_labels + 1):
        label_x = hits[i - 1][1].left
        for j in range(n_piles + 1):
            best, prev = cost[i - 1][j] + gap_cost, (i - 1, j, None)
            if j > 0 and cost[i][j - 1] < best:
                best, prev = cost[i][j - 1], (i, j - 1, None)
            if j > 0:
                delta = label_x - pile_starts[j - 1]
                distance = 0.3 * delta if delta >= 0 else -delta
                assigned = cost[i - 1][j - 1] + distance
                if assigned < best:
                    best, prev = assigned, (i - 1, j - 1, j - 1)
            cost[i][j] = best
            choice[(i, j)] = prev

    assignment: dict[int, int] = {}
    i, j = n_labels, n_piles
    while i > 0 or j > 0:
        pi, pj, pile = choice.get((i, j), (0, 0, None))
        if pile is not None:
            assignment[i - 1] = pile
        i, j = pi, pj

    return [
        (
            float(pile_starts[assignment[k]]) if k in assignment else float(w.left),
            field,
        )
        for k, (field, w) in enumerate(hits)
    ]


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
    # A 5-digit token is unambiguously the PLZ, so when column boundaries are
    # slightly off, rescue it from the neighbouring address cells.
    plz_match = (
        _PLZ.search(text.get("postal_code", ""))
        or _PLZ.search(text.get("street", ""))
        or _PLZ.search(text.get("city", ""))
    )
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
        # Keep the row's printed text as the client (Kunde) verbatim — never
        # substitute the matched store's canonical name, which would erase a
        # real per-row distinction. Store linking happens at commit via
        # store_id; the two are shown side by side, not merged.
        cleaned = _PLZ.sub(" ", line)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -|")
        store = match_store_in_text(db, line, plz)
        stops.append(
            ExtractedStop(
                customer=cleaned or None,
                postal_code=plz,
                city=store.city if store is not None else None,
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
    dates = sorted(_iso_date(d) for d in _DATE.findall(joined))
    employee = _EMPLOYEE.search(joined)
    team_lead = _TEAM_LEAD.search(joined)
    team_no = _TEAM_NO.search(joined)
    vehicle = _VEHICLE.search(joined)
    tour_customer = _TOUR_CUSTOMER.search(joined)

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
            # A long plan may repeat its header (second table section on the
            # same page); a repeat is a divider, not a stop row.
            if not _is_header_row(row)
            and (stop := _row_stop(_bucket_row(row, starts, tolerance))) is not None
        ]
    else:
        stops = _fallback_stops(db, rows)

    return ExtractedTour(
        customer=tour_customer.group(1).strip() if tour_customer else None,
        calendar_week=int(kw.group(1)) if kw else None,
        # min/max over every date on the page beats trusting the meta line's
        # OCR: the stop rows themselves carry the week's range.
        date_from=dates[0] if dates else None,
        date_to=dates[-1] if len(dates) > 1 else None,
        team_lead=_clean_header_value(team_lead.group(1)) if team_lead else None,
        employee=_clean_header_value(employee.group(1)) if employee else None,
        team_no=team_no.group(1).strip() if team_no else None,
        vehicle=_clean_header_value(vehicle.group(1)) if vehicle else None,
        stops=stops,
    )
