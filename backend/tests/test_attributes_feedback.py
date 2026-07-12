"""Store attributes, stop completion, and visit feedback endpoints.

Requires a reachable database with migrations applied; skipped when the DB is
unreachable. No network calls. Uses fictional fixtures and cleans up after.
"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.store import Store
from app.models.tour import Tour
from app.models.visit_feedback import VisitFeedback


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")

client = TestClient(app)


@pytest.fixture
def seeded():
    """A store, a tour, and one stop linked to both; cleaned up after."""
    db = SessionLocal()
    store = Store(name="Testmarkt Feedback", postal_code="99003", city="Teststadt")
    tour = Tour(
        customer="Aldi Nord",
        calendar_week=28,
        date_from=date(2026, 7, 6),
        date_to=date(2026, 7, 10),
    )
    db.add_all([store, tour])
    db.flush()
    stop = Stop(
        tour_id=tour.id,
        store_id=store.id,
        row_index=0,
        customer="Testmarkt Feedback",
    )
    db.add(stop)
    db.commit()
    ids = (store.id, tour.id, stop.id)
    db.close()

    yield ids

    db = SessionLocal()
    db.query(VisitFeedback).filter(VisitFeedback.store_id == ids[0]).delete()
    db.query(Tour).filter(Tour.id == ids[1]).delete()  # cascades to the stop
    db.query(Store).filter(Store.id == ids[0]).delete()
    db.commit()
    db.close()


def test_tour_defaults_to_fixed_date_mode(seeded):
    _, tour_id, _ = seeded
    db = SessionLocal()
    assert db.get(Tour, tour_id).date_mode == "fixed"
    db.close()


def test_store_attributes_capture_and_completeness(seeded):
    store_id, _, _ = seeded

    # A fresh store has nothing captured yet.
    body = client.get(f"/stores/{store_id}").json()
    assert body["attributes_complete"] is False
    assert body["size"] is None

    # Partial capture is not complete and stamps the audit pair.
    resp = client.patch(
        f"/stores/{store_id}/attributes",
        json={"size": "medium", "updated_by": "Jalal"},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["size"] == "medium"
    assert body["attributes_complete"] is False
    assert body["attributes_updated_at"] is not None
    assert body["attributes_updated_by"] == "Jalal"

    # All three captured -> complete.
    body = client.patch(
        f"/stores/{store_id}/attributes",
        json={"in_mall": True, "has_parking": False},
    ).json()
    assert body["attributes_complete"] is True

    # Clearing one attribute drops completeness again.
    body = client.patch(
        f"/stores/{store_id}/attributes", json={"has_parking": None}
    ).json()
    assert body["attributes_complete"] is False

    # An update without any attribute field is rejected.
    resp = client.patch(f"/stores/{store_id}/attributes", json={"updated_by": "X"})
    assert resp.status_code == 422


def test_complete_stop_is_idempotent(seeded):
    _, _, stop_id = seeded

    first = client.post(f"/stops/{stop_id}/complete").json()
    assert first["completed_at"] is not None

    # A repeat call keeps the original timestamp...
    again = client.post(f"/stops/{stop_id}/complete").json()
    assert again["completed_at"] == first["completed_at"]

    # ...unless forced (func.now() is transaction time, so equality would only
    # mean both writes shared a transaction — they don't; assert it's set).
    forced = client.post(f"/stops/{stop_id}/complete", json={"force": True}).json()
    assert forced["completed_at"] is not None

    db = SessionLocal()
    assert db.get(Stop, stop_id).completed_at is not None
    db.close()


def test_uncomplete_stop_clears_completed_at(seeded):
    _, _, stop_id = seeded

    assert client.post(f"/stops/{stop_id}/complete").json()["completed_at"]

    undone = client.delete(f"/stops/{stop_id}/complete")
    assert undone.status_code == 200
    assert undone.json()["completed_at"] is None

    # Idempotent: undoing an already-open stop is a no-op, not an error.
    again = client.delete(f"/stops/{stop_id}/complete")
    assert again.status_code == 200
    assert again.json()["completed_at"] is None


def test_list_stops_carries_store_attribute_state(seeded):
    store_id, tour_id, stop_id = seeded

    [stop] = client.get(f"/tours/{tour_id}/stops").json()
    assert stop["id"] == stop_id
    assert stop["store_id"] == store_id
    # Fresh store: nothing captured yet, so the app should show the form.
    assert stop["store_attributes_complete"] is False

    client.patch(
        f"/stores/{store_id}/attributes",
        json={"size": "small", "in_mall": False, "has_parking": True},
    )
    [stop] = client.get(f"/tours/{tour_id}/stops").json()
    assert stop["store_attributes_complete"] is True


def test_feedback_dedupes_on_client_uuid(seeded):
    store_id, tour_id, stop_id = seeded
    key = str(uuid.uuid4())
    payload = {
        "stop_id": stop_id,
        "client_uuid": key,
        "employee": "Jalal",
        "tags": ["parking_full", "took_longer"],
        "note": "Parkplatz voll, 20 min extra",
    }

    first = client.post("/feedback", json=payload)
    assert first.status_code == 201
    body = first.json()
    # tour_id/store_id are derived from the stop server-side.
    assert body["tour_id"] == tour_id
    assert body["store_id"] == store_id

    # An offline-sync retry returns the same row instead of creating another.
    second = client.post("/feedback", json=payload)
    assert second.status_code == 200
    assert second.json()["id"] == body["id"]

    rows = client.get(f"/feedback?stop_id={stop_id}").json()
    assert [r["client_uuid"] for r in rows] == [key]

    # Tags outside the controlled vocabulary are rejected.
    bad = client.post(
        "/feedback",
        json={"stop_id": stop_id, "client_uuid": str(uuid.uuid4()), "tags": ["nice"]},
    )
    assert bad.status_code == 422
