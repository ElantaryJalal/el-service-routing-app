"""Commit-time store resolution (services.store_resolution).

Acceptance:
- committing a plan against a populated catalog performs ZERO geocoding and
  links every stop;
- a row with a typo'd street still matches its store and is flagged as an
  address mismatch instead of creating a duplicate store;
- an ambiguous match is surfaced for the dispatcher, never auto-linked.

Requires a reachable database with migrations applied; skipped otherwise.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

import app.api.tours as tours_api
from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.store import AddressProvenance, Store
from app.models.tour import Tour
from app.services.store_resolution import claim_matches_store, resolve_stop


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")

client = TestClient(app)

_PREFIX = "Resolution-Test"


@pytest.fixture
def catalog():
    """Two verified stores, far apart in address space, plus one near-twin
    pair that makes fuzzy matching genuinely ambiguous."""
    db = SessionLocal()
    stores = [
        Store(
            name=f"{_PREFIX} Gohlis",
            street="Georg-Schumann-Str. 100",
            postal_code="99201",
            city="Teststadt",
            geom="SRID=4326;POINT(12.36 51.37)",
        ),
        Store(
            name=f"{_PREFIX} Connewitz",
            street="Bornaische Str. 50",
            postal_code="99202",
            city="Teststadt",
            geom="SRID=4326;POINT(12.38 51.31)",
        ),
        # Near-twins: same street name, adjacent numbers, same city.
        Store(
            name=f"{_PREFIX} Twin Nord",
            street="Zwillingsallee 10",
            postal_code="99203",
            city="Teststadt",
            geom="SRID=4326;POINT(12.40 51.40)",
        ),
        Store(
            name=f"{_PREFIX} Twin Sued",
            street="Zwillingsallee 12",
            postal_code="99203",
            city="Teststadt",
            geom="SRID=4326;POINT(12.41 51.41)",
        ),
    ]
    db.add_all(stores)
    db.commit()
    ids = [s.id for s in stores]
    db.close()

    yield ids

    db = SessionLocal()
    db.query(Stop).filter(Stop.store_id.in_(ids)).delete(synchronize_session=False)
    db.query(Store).filter(Store.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    db.close()


@pytest.fixture
def tour(catalog):
    db = SessionLocal()
    tour = Tour(
        customer="Resolution-Test Tour",
        calendar_week=41,
        date_from=date(2026, 10, 5),
        date_to=date(2026, 10, 9),
    )
    db.add(tour)
    db.commit()
    tour_id = tour.id
    db.close()

    yield tour_id

    db = SessionLocal()
    db.query(Stop).filter(Stop.tour_id == tour_id).delete()
    db.query(Tour).filter(Tour.id == tour_id).delete()
    db.query(Store).filter(Store.name.like("Neuer Markt%")).delete(
        synchronize_session=False
    )
    db.commit()
    db.close()


def _add_stop(tour_id, customer, street=None, plz=None, city=None):
    db = SessionLocal()
    max_row = (
        db.query(Stop.row_index)
        .filter(Stop.tour_id == tour_id)
        .order_by(Stop.row_index.desc())
        .first()
    )
    stop = Stop(
        tour_id=tour_id,
        row_index=(max_row[0] + 1) if max_row else 0,
        customer=customer,
        claimed_street=street,
        claimed_postal_code=plz,
        claimed_city=city,
        status="unconfirmed",
    )
    db.add(stop)
    db.commit()
    stop_id = stop.id
    db.close()
    return stop_id


def _forbid_geocode(monkeypatch):
    calls = []

    def _fail(db, *a, **k):
        calls.append(a)
        return None

    monkeypatch.setattr(tours_api, "geocode_address", _fail)
    return calls


def test_commit_links_all_without_geocoding(tour, monkeypatch):
    """A plan of known stores commits with zero geocoding calls, every stop
    linked; the typo'd row matches its store and is flagged, not duplicated."""
    geocode_calls = _forbid_geocode(monkeypatch)
    monkeypatch.setattr(tours_api, "fetch_opening_hours", lambda *a, **k: None)

    clean = _add_stop(
        tour, "Gohlis Markt", "Georg-Schumann-Str. 100", "99201", "Teststadt"
    )
    # Typo'd street ("Schumman"), correct PLZ/city: fuzzy >= 90 still hits.
    typo = _add_stop(
        tour, "Connewitz Markt", "Bornaische Str. 5O", "99202", "Teststadt"
    )

    resp = client.post(f"/tours/{tour}/commit")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert geocode_calls == []  # ZERO geocoding against a populated catalog
    assert body["stops_matched"] == 2
    assert body["new_stores"] == []
    assert body["review_items"] == []

    db = SessionLocal()
    clean_stop, typo_stop = db.get(Stop, clean), db.get(Stop, typo)
    assert clean_stop.store_id is not None
    assert typo_stop.store_id is not None
    assert clean_stop.address_matches_store is True
    # The typo'd row matched its store but is FLAGGED, and both values kept.
    assert typo_stop.address_matches_store is False
    assert typo_stop.claimed_street == "Bornaische Str. 5O"  # audit trail
    db.close()

    flagged = {m["stop_id"] for m in body["address_mismatches"]}
    assert flagged == {typo}

    # Re-committing the same plan stays geocode-free and fully linked.
    resp = client.post(f"/tours/{tour}/commit")
    assert resp.status_code == 200
    assert geocode_calls == []
    assert resp.json()["stops_matched"] == 2


def test_ambiguous_match_is_surfaced_not_linked(tour, monkeypatch):
    """A claim fitting two near-twin stores equally well must become a review
    item — a false link silently sends the crew to the wrong store."""
    _forbid_geocode(monkeypatch)
    monkeypatch.setattr(tours_api, "fetch_opening_hours", lambda *a, **k: None)

    # Number 11 sits between the twins at 10 and 12 — both score high.
    ambiguous = _add_stop(tour, "Twin Markt", "Zwillingsallee 11", "99203", "Teststadt")

    body = client.post(f"/tours/{tour}/commit").json()

    items = {i["stop_id"]: i for i in body["review_items"]}
    assert ambiguous in items
    assert len(items[ambiguous]["candidates"]) >= 2
    db = SessionLocal()
    assert db.get(Stop, ambiguous).store_id is None  # never auto-linked
    db.close()


def test_unmatched_row_becomes_reported_new_store(tour, monkeypatch):
    """A row matching nothing geocodes once and becomes a candidate store
    with address_provenance='geocoded' — reported, not silent."""
    monkeypatch.setattr(
        tours_api, "geocode_address", lambda db, *a, **k: (12.99, 51.99)
    )
    monkeypatch.setattr(tours_api, "fetch_opening_hours", lambda *a, **k: None)

    new = _add_stop(tour, "Neuer Markt", "Unbekannte Str. 7", "99999", "Anderstadt")
    body = client.post(f"/tours/{tour}/commit").json()

    assert [n["stop_id"] for n in body["new_stores"]] == [new]
    db = SessionLocal()
    stop = db.get(Stop, new)
    assert stop.store_id is not None
    store = db.get(Store, stop.store_id)
    assert store.address_provenance == AddressProvenance.geocoded
    assert store.geom is not None
    db.close()


def test_order_no_matches_only_when_history_is_unanimous():
    """A number that ever pointed at two stores must never match (the guard
    that makes rule 1 safe even if order numbers turn out per-tour)."""
    db = SessionLocal()
    store = Store(name=f"{_PREFIX} OrderNo", postal_code="99204", city="Teststadt")
    db.add(store)
    db.flush()

    stop = Stop(tour_id=0, row_index=0, claimed_order_no="0042")
    # Unanimous history: matches.
    res = resolve_stop(
        stop,
        [store],
        by_order_no={"0042": store.id},
        coords={},
        claim_coord=None,
    )
    assert res.outcome == "linked" and res.rule == "order_no"

    # Not in the unanimous index (conflicted history): falls through.
    res = resolve_stop(stop, [store], by_order_no={}, coords={}, claim_coord=None)
    assert res.outcome == "unresolved"

    db.rollback()
    db.close()


def test_claim_matches_store_compares_only_printed_fields():
    store = Store(name="X", street="Hauptstr. 5", postal_code="04109", city="Leipzig")
    # Abbreviation/case differences are not a mismatch.
    ok = Stop(claimed_street="hauptstrasse 5", claimed_postal_code="04109")
    assert claim_matches_store(ok, store) is True
    # A wrong printed PLZ is.
    bad = Stop(claimed_street="Hauptstr. 5", claimed_postal_code="04177")
    assert claim_matches_store(bad, store) is False
    # No printed address at all: nothing to check.
    assert claim_matches_store(Stop(), store) is None
