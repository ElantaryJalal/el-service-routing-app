"""Local OCR extraction: header-driven column parsing of a plan's word boxes.

Requires a reachable database (the fallback path resolves against the
catalog); skipped otherwise. Tesseract is stubbed via `_ocr_words`, so the
test needs no OCR binary. Uses fictional stores and postal codes so it's
independent of any seeded catalog.
"""

import pytest
from geoalchemy2.elements import WKTElement

import app.services.extraction_local as local
from app.db import SessionLocal, engine
from app.models.store import Store
from app.services.extraction_local import Word


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")


def _words(layout: list[list[tuple[int, str]]], conf: float = 95.0) -> list[Word]:
    """Build positioned OCR words from rows of (x, text) cells.

    Each row sits 40px below the previous; a multi-word cell text becomes
    consecutive words so column bucketing sees realistic input.
    """
    words: list[Word] = []
    for row_index, row in enumerate(layout):
        top = 40 * row_index
        for left, text in row:
            x = left
            for token in text.split():
                words.append(
                    Word(
                        text=token,
                        left=x,
                        top=top,
                        width=9 * len(token),
                        height=16,
                        conf=conf,
                    )
                )
                x += 9 * len(token) + 9
    return words


# Column x-origins mirror a printed plan's layout.
_COLS = dict(
    tag=0, markt=100, nr=350, strasse=450, plz=650, ort=730, aufgaben=880, min=1020
)

# A misread store name ("Nrdstern"), a street number that must NOT be taken as
# the service time, and a store that is NOT in the catalog ("Rewe Fantasia").
_PLAN = [
    [(0, "EL Service GmbH Tourenplan")],
    [(0, "KW 28 06.07.2026 - 10.07.2026 | Mitarbeiter: M. Krause")],
    [
        (_COLS["tag"], "Tag"),
        (_COLS["markt"], "Markt"),
        (_COLS["nr"], "Nr"),
        (_COLS["strasse"], "Strasse"),
        (_COLS["plz"], "PLZ"),
        (_COLS["ort"], "Ort"),
        (_COLS["aufgaben"], "Aufgaben"),
        (_COLS["min"], "Min"),
    ],
    [
        (_COLS["tag"], "Mo"),
        (_COLS["markt"], "Testmarkt Nordstern"),
        (_COLS["nr"], "4711"),
        (_COLS["strasse"], "Teststr 1"),
        (_COLS["plz"], "99001"),
        (_COLS["ort"], "Teststadt"),
        (_COLS["aufgaben"], "EKW"),
        (_COLS["min"], "60"),
    ],
    [
        (_COLS["tag"], "Mo"),
        (_COLS["markt"], "Testmarkt Nrdstern"),
        (_COLS["nr"], "4712"),
        (_COLS["strasse"], "Langstr 100"),
        (_COLS["plz"], "99001"),
        (_COLS["ort"], "Teststadt"),
        (_COLS["aufgaben"], "EKW"),
        (_COLS["min"], "8"),
    ],
    [
        (_COLS["tag"], "Di"),
        (_COLS["markt"], "Testmarkt Suedwind"),
        (_COLS["nr"], "4713"),
        (_COLS["strasse"], "Testweg 2"),
        (_COLS["plz"], "99002"),
        (_COLS["ort"], "Andersstadt"),
        (_COLS["aufgaben"], "EKW, Boden"),
        (_COLS["min"], "50"),
    ],
    [
        (_COLS["tag"], "Di"),
        (_COLS["markt"], "Rewe Fantasia"),
        (_COLS["nr"], "55510"),
        (_COLS["strasse"], "Nowherestr 7"),
        (_COLS["plz"], "12399"),
        (_COLS["ort"], "Nowhere"),
        (_COLS["aufgaben"], "Grundreinigung"),
        (_COLS["min"], "70"),
    ],
]


@pytest.fixture
def catalog():
    db = SessionLocal()
    nord = Store(
        name="Testmarkt Nordstern",
        street="Teststr. 1",
        postal_code="99001",
        city="Teststadt",
        geom=WKTElement("POINT(12.38 51.31)", srid=4326),
        default_tasks=["EKW"],
        default_service_minutes=45,
    )
    sued = Store(
        name="Testmarkt Suedwind",
        street="Testweg 2",
        postal_code="99002",
        city="Andersstadt",
        geom=WKTElement("POINT(11.99 51.35)", srid=4326),
        default_tasks=["EKW"],
        default_service_minutes=60,
    )
    db.add_all([nord, sued])
    db.commit()
    ids = (nord.id, sued.id)
    db.close()
    yield ids
    db = SessionLocal()
    db.query(Store).filter(Store.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    db.close()


def test_header_driven_parsing_reads_every_row(monkeypatch):
    monkeypatch.setattr(local, "_ocr_words", lambda image_bytes, langs: _words(_PLAN))
    monkeypatch.setattr(local, "_ocr_words_sparse", lambda image_bytes, langs: [])
    db = SessionLocal()

    tour = local.extract_tour_local(db, b"fake-image", "image/png")
    db.close()

    # Header parsed from the meta line.
    assert tour.calendar_week == 28
    assert tour.date_from == "2026-07-06"
    assert tour.date_to == "2026-07-10"
    assert tour.employee.startswith("M. Krause")

    # EVERY data row is extracted — including the store that is not in the
    # catalog ("Rewe Fantasia"): the catalog enriches, it never filters.
    assert [s.customer for s in tour.stops] == [
        "Testmarkt Nordstern",
        "Testmarkt Nrdstern",  # raw read; the endpoint's catalog match fixes it
        "Testmarkt Suedwind",
        "Rewe Fantasia",
    ]

    # Columns land in the right fields: the PLZ is never confused with the
    # order number (even the 5-digit order "55510"), the street keeps its
    # house number, tasks split on commas.
    assert [s.postal_code for s in tour.stops] == ["99001", "99001", "99002", "12399"]
    assert [s.order_no for s in tour.stops] == ["4711", "4712", "4713", "55510"]
    assert [s.street for s in tour.stops] == [
        "Teststr 1",
        "Langstr 100",
        "Testweg 2",
        "Nowherestr 7",
    ]
    assert tour.stops[2].tasks == ["EKW", "Boden"]
    assert [s.weekday for s in tour.stops] == ["Mo", "Mo", "Di", "Di"]
    assert [s.date for s in tour.stops] == [None] * 4

    # service_minutes: in-range values read; the bad-OCR "8" is out of range
    # -> None (catalog default fills it later); street numbers never leak in.
    assert [s.service_minutes for s in tour.stops] == [60, None, 50, 70]


def test_low_confidence_words_flag_their_field(monkeypatch):
    monkeypatch.setattr(
        local, "_ocr_words", lambda image_bytes, langs: _words(_PLAN, conf=42.0)
    )
    monkeypatch.setattr(local, "_ocr_words_sparse", lambda image_bytes, langs: [])
    db = SessionLocal()
    tour = local.extract_tour_local(db, b"fake-image", "image/png")
    db.close()

    flagged = tour.stops[0].confidence
    assert flagged.street == 0.42
    assert flagged.postal_code == 0.42


def test_fallback_without_header_keeps_unknown_rows(monkeypatch, catalog):
    # No recognizable header row: plain address lines only.
    layout = [
        [(0, "KW 28 06.07.2026 - 10.07.2026")],
        [(0, "Testmarkt Nordstern Teststr 1 99001 Teststadt EKW 60")],
        [(0, "Rewe Fantasia Nowherestr 7 12399 Nowhere 70")],
    ]
    monkeypatch.setattr(local, "_ocr_words", lambda image_bytes, langs: _words(layout))
    db = SessionLocal()

    tour = local.extract_tour_local(db, b"fake-image", "image/png")
    db.close()

    # Every row keeps its printed text as the client verbatim — even the one
    # that matches a catalog store. The store link is made later (at commit via
    # store_id); the printed Kunde is never overwritten with the store's
    # canonical name, so a real per-row distinction can't be erased.
    assert [s.customer for s in tour.stops] == [
        "Testmarkt Nordstern Teststr 1 Teststadt EKW 60",
        "Rewe Fantasia Nowherestr 7 Nowhere 70",
    ]
    assert [s.postal_code for s in tour.stops] == ["99001", "12399"]
    assert tour.stops[1].remarks == "Rewe Fantasia Nowherestr 7 12399 Nowhere 70"


def test_clean_header_value_strips_internal_codes():
    # Adjacent labels / internal codes bleed into a greedy name capture; they
    # must be trimmed so "Gewerke"/"VFL"/"VDP"/"Team-Nr." never become a name.
    assert local._clean_header_value("Sophie Lehmann Gewerke VFL") == "Sophie Lehmann"
    assert local._clean_header_value("Halil Ibrahim Team-Nr. SYS-R") == "Halil Ibrahim"
    assert local._clean_header_value("Gewerke VFL") is None
    assert local._clean_header_value("  Max Mustermann  ") == "Max Mustermann"


def test_header_parses_team_no_and_vehicle_without_noise(monkeypatch, catalog):
    layout = [
        [(0, "Teamleiter: Sophie Lehmann Gewerke VFL")],
        [(0, "Mitarbeiter: Max Mustermann")],
        [(0, "Team-Nr.: SYS-R Fahrzeug: AC EL 987")],
        [(0, "Testmarkt Nordstern Teststr 1 99001 Teststadt EKW 60")],
    ]
    monkeypatch.setattr(local, "_ocr_words", lambda image_bytes, langs: _words(layout))
    db = SessionLocal()
    tour = local.extract_tour_local(db, b"fake-image", "image/png")
    db.close()

    assert tour.team_lead == "Sophie Lehmann"
    assert tour.employee == "Max Mustermann"
    assert tour.team_no == "SYS-R"
    assert tour.vehicle == "AC EL 987"
