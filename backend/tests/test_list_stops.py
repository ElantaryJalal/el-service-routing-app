"""Integration test for GET /tours/{id}/stops.

Requires a reachable database with migrations applied (see infra/README.md).
Skipped automatically when the DB is unreachable.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from geoalchemy2.elements import WKTElement

from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.task import Task
from app.models.tour import Tour


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")


@pytest.fixture
def seeded():
    """A tour with a geocoded stop (two tasks) and an ungeocoded stop."""
    db = SessionLocal()
    tour = Tour(
        customer="Aldi Nord",
        calendar_week=27,
        date_from=date(2026, 6, 29),
        date_to=date(2026, 7, 3),
    )
    db.add(tour)
    db.flush()
    # row_index deliberately out of insertion order to prove ordering.
    with_geom = Stop(
        tour_id=tour.id,
        row_index=1,
        customer="Aldi geocoded",
        street="Hauptstr. 1",
        postal_code="04109",
        city="Leipzig",
        service_minutes=45,
        geom=WKTElement("POINT(12.3731 51.3397)", srid=4326),
    )
    no_geom = Stop(
        tour_id=tour.id,
        row_index=0,
        customer="Aldi no-geom",
    )
    db.add_all([with_geom, no_geom])
    db.flush()
    db.add_all(
        [
            Task(stop_id=with_geom.id, task_type="EKW", raw_label="Eingangskontrolle"),
            Task(stop_id=with_geom.id, task_type="FUSSMATTEN", raw_label=None),
        ]
    )
    db.commit()
    ids = (tour.id, with_geom.id, no_geom.id)
    db.close()

    yield ids

    db = SessionLocal()
    db.query(Task).filter(Task.stop_id.in_([ids[1], ids[2]])).delete(
        synchronize_session=False
    )
    db.query(Stop).filter(Stop.tour_id == ids[0]).delete()
    db.query(Tour).filter(Tour.id == ids[0]).delete()
    db.commit()
    db.close()


def test_list_stops_returns_coords_address_and_tasks(seeded):
    tour_id, geo_id, nogeo_id = seeded
    client = TestClient(app)

    resp = client.get(f"/tours/{tour_id}/stops")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Ordered by row_index: ungeocoded (0) then geocoded (1).
    assert [s["id"] for s in body] == [nogeo_id, geo_id]

    nogeo, geo = body
    # Ungeocoded stop has null coordinates and no tasks.
    assert nogeo["lat"] is None and nogeo["lng"] is None
    assert nogeo["tasks"] is None

    # Geocoded stop carries lat/lng, address, and joined task labels
    # (raw_label preferred, task_type as fallback).
    assert geo["lat"] == pytest.approx(51.3397)
    assert geo["lng"] == pytest.approx(12.3731)
    assert geo["street"] == "Hauptstr. 1"
    assert geo["postal_code"] == "04109"
    assert geo["city"] == "Leipzig"
    assert geo["service_minutes"] == 45
    assert geo["tasks"] == "Eingangskontrolle, FUSSMATTEN"


def test_list_stops_unknown_tour_404():
    client = TestClient(app)
    resp = client.get("/tours/999999999/stops")
    assert resp.status_code == 404
