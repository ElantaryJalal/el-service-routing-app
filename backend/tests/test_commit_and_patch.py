"""Integration test for tour commit (store hours enrichment) and stop PATCH.

Hours live on the *store* since 0012: commit enriches the linked store's
hours from OSM, and a manual PATCH on a stop writes through to its store.

Requires a reachable database with migrations applied (see infra/README.md).
Skipped automatically when the DB is unreachable. Overpass is monkeypatched so
the test never touches the network.
"""

from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from geoalchemy2.elements import WKTElement

import app.api.tours as tours_api
from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.store import HoursSource, Store
from app.models.tour import Tour


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")


def _returns(window):
    """Build a fetch_opening_hours stub returning a fixed window."""

    def _stub(lon, lat, **kwargs):
        return window

    return _stub


@pytest.fixture
def seeded():
    """A tour with one store-linked stop and one unresolved (storeless) stop."""
    db = SessionLocal()
    tour = Tour(
        customer="Aldi Nord",
        calendar_week=27,
        date_from=date(2026, 6, 29),
        date_to=date(2026, 7, 3),
    )
    db.add(tour)
    db.flush()
    store = Store(
        name="Commit-Test Markt",
        street="Teststr. 1",
        postal_code="99981",
        city="Testhausen",
        geom=WKTElement("POINT(12.3731 51.3397)", srid=4326),
    )
    db.add(store)
    db.flush()
    linked = Stop(
        tour_id=tour.id,
        row_index=0,
        customer="Aldi geocoded",
        store_id=store.id,
    )
    # No claimed address, no store: commit creates a candidate store for it.
    unresolved = Stop(tour_id=tour.id, row_index=1, customer="Aldi no-geom")
    db.add_all([linked, unresolved])
    db.commit()
    ids = (tour.id, linked.id, unresolved.id, store.id)
    db.close()

    yield ids

    db = SessionLocal()
    db.query(Stop).filter(Stop.tour_id == ids[0]).delete()
    db.query(Tour).filter(Tour.id == ids[0]).delete()
    # The fixture store, plus whatever candidate store commit created for the
    # unresolved row — the dev catalog must stay clean.
    db.query(Store).filter(
        Store.name.in_(["Commit-Test Markt", "Aldi no-geom"])
    ).delete()
    db.commit()
    db.close()


def test_commit_enriches_and_manual_patch_wins(seeded, monkeypatch):
    tour_id, linked_id, unresolved_id, store_id = seeded
    monkeypatch.setattr(
        tours_api, "fetch_opening_hours", _returns((time(8, 0), time(20, 0)))
    )
    client = TestClient(app)

    # --- Commit: OSM hours land on the geocoded store only ---
    resp = client.post(f"/tours/{tour_id}/commit")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "planned"
    assert body["stops_total"] == 2
    assert body["stops_enriched"] == 1
    # The storeless row became a candidate new store — reported, not silent.
    assert [n["stop_id"] for n in body["new_stores"]] == [unresolved_id]

    db = SessionLocal()
    store = db.get(Store, store_id)
    assert store.opening_time == time(8, 0)
    assert store.closing_time == time(20, 0)
    assert store.hours_source == HoursSource.osm
    linked = db.get(Stop, linked_id)
    unresolved = db.get(Stop, unresolved_id)
    # Stops read hours through the store; the new candidate store has none.
    assert linked.effective_hours == (time(8, 0), time(20, 0))
    assert unresolved.store_id is not None
    assert unresolved.effective_hours == (None, None)
    assert unresolved.effective_hours_source == HoursSource.default
    # Commit confirms the tour's stops so the optimiser will schedule them.
    assert linked.status == "confirmed"
    assert unresolved.status == "confirmed"
    new_store_id = unresolved.store_id
    db.close()

    # --- Manual PATCH writes through to the store, hours_source 'manual' ---
    resp = client.patch(f"/stops/{unresolved_id}", json={"closing_time": "13:00:00"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["closing_time"] == "13:00:00"
    assert resp.json()["hours_source"] == "manual"
    db = SessionLocal()
    assert db.get(Store, new_store_id).closing_time == time(13, 0)
    db.close()

    # service_minutes override validates the 30–600 bound.
    too_low = client.patch(f"/stops/{unresolved_id}", json={"service_minutes": 10})
    assert too_low.status_code == 422
    ok = client.patch(f"/stops/{unresolved_id}", json={"service_minutes": 45})
    assert ok.status_code == 200

    # --- Manual override must win over re-commit ---
    client.patch(f"/stops/{linked_id}", json={"closing_time": "15:00:00"})
    monkeypatch.setattr(
        tours_api, "fetch_opening_hours", _returns((time(9, 0), time(17, 0)))
    )
    resp = client.post(f"/tours/{tour_id}/commit")
    assert resp.status_code == 200
    assert resp.json()["stops_enriched"] == 0

    db = SessionLocal()
    store = db.get(Store, store_id)
    assert store.hours_source == HoursSource.manual
    assert store.closing_time == time(15, 0)
    db.close()


def test_patch_hours_without_store_is_rejected(seeded):
    """A stop with no linked store has nowhere to hold hours."""
    tour_id, _, unresolved_id, _ = seeded
    client = TestClient(app)
    # Before commit the unresolved stop has no store yet.
    resp = client.patch(f"/stops/{unresolved_id}", json={"closing_time": "12:00:00"})
    assert resp.status_code == 422
    assert "no linked store" in resp.json()["detail"]
