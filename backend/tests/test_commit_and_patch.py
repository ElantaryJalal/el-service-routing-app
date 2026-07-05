"""Integration test for tour commit (OSM hours enrichment) and stop PATCH.

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
from app.models.stop import HoursSource, Stop
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
    """A tour with one geocoded stop and one without a geom."""
    db = SessionLocal()
    tour = Tour(
        customer="Aldi Nord",
        calendar_week=27,
        date_from=date(2026, 6, 29),
        date_to=date(2026, 7, 3),
    )
    db.add(tour)
    db.flush()
    with_geom = Stop(
        tour_id=tour.id,
        row_index=0,
        customer="Aldi geocoded",
        geom=WKTElement("POINT(12.3731 51.3397)", srid=4326),
    )
    no_geom = Stop(tour_id=tour.id, row_index=1, customer="Aldi no-geom")
    db.add_all([with_geom, no_geom])
    db.commit()
    ids = (tour.id, with_geom.id, no_geom.id)
    db.close()

    yield ids

    db = SessionLocal()
    db.query(Stop).filter(Stop.tour_id == ids[0]).delete()
    db.query(Tour).filter(Tour.id == ids[0]).delete()
    db.commit()
    db.close()


def test_commit_enriches_and_manual_patch_wins(seeded, monkeypatch):
    tour_id, geo_id, nogeo_id = seeded
    monkeypatch.setattr(
        tours_api, "fetch_opening_hours", _returns((time(8, 0), time(20, 0)))
    )
    client = TestClient(app)

    # --- Commit: OSM hours populate the geocoded stop only ---
    resp = client.post(f"/tours/{tour_id}/commit")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "confirmed"
    assert body["stops_total"] == 2
    assert body["stops_enriched"] == 1

    db = SessionLocal()
    geo = db.get(Stop, geo_id)
    nogeo = db.get(Stop, nogeo_id)
    assert geo.opening_time == time(8, 0)
    assert geo.closing_time == time(20, 0)
    assert geo.hours_source == HoursSource.osm
    assert nogeo.closing_time is None
    assert nogeo.hours_source == HoursSource.default
    # Commit confirms the tour's stops so the optimiser will schedule them.
    assert geo.status == "confirmed"
    assert nogeo.status == "confirmed"
    db.close()

    # --- Manual PATCH sticks and flips hours_source to 'manual' ---
    resp = client.patch(f"/stops/{nogeo_id}", json={"closing_time": "13:00:00"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["closing_time"] == "13:00:00"
    assert resp.json()["hours_source"] == "manual"

    # service_minutes override validates the 30–600 bound.
    too_low = client.patch(f"/stops/{nogeo_id}", json={"service_minutes": 10})
    assert too_low.status_code == 422
    ok = client.patch(f"/stops/{nogeo_id}", json={"service_minutes": 45})
    assert ok.status_code == 200

    # --- Manual override must win over re-commit ---
    client.patch(f"/stops/{geo_id}", json={"closing_time": "15:00:00"})
    monkeypatch.setattr(
        tours_api, "fetch_opening_hours", _returns((time(9, 0), time(17, 0)))
    )
    resp = client.post(f"/tours/{tour_id}/commit")
    assert resp.status_code == 200
    assert resp.json()["stops_enriched"] == 0

    db = SessionLocal()
    geo = db.get(Stop, geo_id)
    assert geo.hours_source == HoursSource.manual
    assert geo.closing_time == time(15, 0)
    db.close()
