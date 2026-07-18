"""Integration test for the ingestion flow: extract -> draft -> patch.

Requires a reachable database with migrations applied (see infra/README.md);
skipped automatically when the DB is unreachable. Both the vision extraction and
Nominatim geocoding are monkeypatched, so the test never touches the network or
the Anthropic API.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

import app.api.tours as tours_api
from app.config import settings
from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.tour import Tour
from app.services.extraction import ExtractedStop, ExtractedTour, StopConfidence


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")


_SAMPLE = ExtractedTour(
    customer="Aldi Nord",
    calendar_week=28,
    date_from="2026-07-06",
    date_to="2026-07-10",
    employee="Demo Employee",
    stops=[
        ExtractedStop(
            customer="Aldi Zentrum",
            street="Markt 1",
            postal_code="04109",
            city="Leipzig",
            tasks=["EKW", "Fussmatten"],
            service_minutes=60,
            confidence=StopConfidence(street=0.4),  # low -> flagged in Confirm
        ),
        ExtractedStop(
            customer="Aldi ungeocodable",
            street=None,
            postal_code=None,
            city=None,
            tasks=[],
            service_minutes=45,
        ),
    ],
)


def _fake_geocode(db, street, postal_code, city, **kwargs):
    # Only the first stop has an address; return a fixed Leipzig point for it.
    if street and city:
        return (12.3731, 51.3397)
    return None


@pytest.fixture
def cleanup_tours():
    created: list[int] = []
    yield created
    db = SessionLocal()
    for tour_id in created:
        db.query(Stop).filter(Stop.tour_id == tour_id).delete()
        db.query(Tour).filter(Tour.id == tour_id).delete()
    db.commit()
    db.close()


def test_extract_then_draft_then_patch(monkeypatch, cleanup_tours):
    # Exercise the vision provider path (stubbed); the local OCR path is covered
    # by test_extraction_local.
    monkeypatch.setattr(settings, "extraction_provider", "anthropic")
    monkeypatch.setattr(tours_api, "extract_tour", lambda data, mt: _SAMPLE)
    monkeypatch.setattr(tours_api, "geocode_address", _fake_geocode)
    # This test exercises the geocode path; catalog matching is covered by
    # test_store_catalog (a matched stop would skip geocoding entirely).
    monkeypatch.setattr(tours_api, "match_store", lambda *a, **k: None)
    client = TestClient(app)

    # --- Extract: a draft tour with two stops in row order ---
    resp = client.post(
        "/tours/extract",
        files={"image": ("plan.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    draft = resp.json()
    tour_id = draft["tour_id"]
    cleanup_tours.append(tour_id)

    assert len(draft["stops"]) == 2
    first, second = draft["stops"]
    assert first["street"] == "Markt 1"
    assert first["tasks"] == "EKW, Fussmatten"
    assert first["service_minutes"] == 60
    assert first["confidence"] == {"street": 0.4}  # low-confidence flag preserved
    assert second["street"] is None
    assert second["confidence"] == {}

    # The tour is a draft; the geocoded stop carries a geom, the other doesn't.
    db = SessionLocal()
    tour = db.get(Tour, tour_id)
    assert tour.status == "draft"
    assert tour.calendar_week == 28
    assert tour.date_from == date(2026, 7, 6)
    stops = (
        db.query(Stop).filter(Stop.tour_id == tour_id).order_by(Stop.row_index).all()
    )
    assert stops[0].claimed_geom is not None and stops[0].status == "unconfirmed"
    assert stops[1].claimed_geom is None
    db.close()

    # --- GET draft returns the same shape ---
    resp = client.get(f"/tours/{tour_id}/draft")
    assert resp.status_code == 200, resp.text
    assert resp.json()["stops"][0]["street"] == "Markt 1"

    # --- PATCH: correcting the street clears its flag and re-geocodes ---
    stop_id = first["id"]
    resp = client.patch(
        f"/tours/{tour_id}/draft/stops/{stop_id}",
        json={"street": "Markt 2", "tasks": "EKW"},
    )
    assert resp.status_code == 200, resp.text
    patched = resp.json()
    assert patched["street"] == "Markt 2"
    assert patched["tasks"] == "EKW"  # tasks re-split from the comma string
    assert patched["confidence"] == {}  # edited field no longer flagged

    # service_minutes bound is enforced (30–600).
    too_low = client.patch(
        f"/tours/{tour_id}/draft/stops/{stop_id}", json={"service_minutes": 5}
    )
    assert too_low.status_code == 422

    # --- 404s for unknown tour / stop ---
    assert client.get("/tours/99999999/draft").status_code == 404
    assert (
        client.patch(
            f"/tours/{tour_id}/draft/stops/99999999", json={"city": "X"}
        ).status_code
        == 404
    )
