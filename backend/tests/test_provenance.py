"""Provenance surfacing and upgrades.

- Completing a stop is field confirmation: the worker physically stood at the
  store, so its geom_provenance upgrades to 'field_confirmed'.
- POST /stops/{id}/resolve-address settles a plan-vs-store mismatch in one
  click: keep the store (default) or update the store from the claim. The
  claim itself is never edited — it is the audit trail.

Requires a reachable database with migrations applied; skipped otherwise.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.store import AddressProvenance, GeomProvenance, Store
from app.models.tour import Tour, TourStatus


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")

client = TestClient(app)


@pytest.fixture
def world():
    """An assigned tour with one store-linked stop carrying a claim typo."""
    db = SessionLocal()
    store = Store(
        name="Provenance-Test Markt",
        street="Wahrestr. 1",
        postal_code="99301",
        city="Teststadt",
        geom="SRID=4326;POINT(12.30 51.30)",
        address_provenance=AddressProvenance.verified,
    )
    tour = Tour(
        customer="Provenance-Test Tour",
        calendar_week=42,
        date_from=date(2026, 10, 12),
        date_to=date(2026, 10, 16),
        status=TourStatus.assigned,
    )
    db.add_all([store, tour])
    db.flush()
    stop = Stop(
        tour_id=tour.id,
        row_index=0,
        customer="Provenance Markt",
        store_id=store.id,
        claimed_street="Falschestr. 9",  # the printed typo
        claimed_postal_code="99301",
        claimed_city="Teststadt",
        address_matches_store=False,
        status="confirmed",
    )
    db.add(stop)
    db.commit()
    ids = (tour.id, stop.id, store.id)
    db.close()

    yield ids

    db = SessionLocal()
    db.query(Stop).filter(Stop.tour_id == ids[0]).delete()
    db.query(Tour).filter(Tour.id == ids[0]).delete()
    db.query(Store).filter(Store.id == ids[2]).delete()
    db.commit()
    db.close()


def test_completion_field_confirms_the_store(world):
    tour_id, stop_id, store_id = world

    resp = client.post(f"/stops/{stop_id}/complete")
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    store = db.get(Store, store_id)
    assert store.geom_provenance == GeomProvenance.field_confirmed
    assert store.verified_at is not None
    # The authenticated user (conftest override) is the confirming identity.
    assert store.verified_by == "Test Override Admin"
    # Address provenance is untouched — only the pin was proven.
    assert store.address_provenance == AddressProvenance.verified
    db.close()


def test_start_stamps_started_at_idempotently(world):
    """POST /stops/{id}/start records the service-start moment, keeps it on a
    repeat (offline-sync retry), and re-stamps only when forced."""
    _, stop_id, _ = world

    body = client.post(f"/stops/{stop_id}/start").json()
    assert body["started_at"] is not None
    assert body["start_source"] == "manual"
    first = body["started_at"]

    # Idempotent: a repeat keeps the original stamp.
    again = client.post(f"/stops/{stop_id}/start").json()
    assert again["started_at"] == first

    # force is allowed and re-stamps.
    forced = client.post(f"/stops/{stop_id}/start", json={"force": True})
    assert forced.status_code == 200, forced.text
    assert forced.json()["started_at"] is not None

    db = SessionLocal()
    stop = db.get(Stop, stop_id)
    assert stop.started_at is not None
    assert stop.start_source.value == "manual"
    db.close()


def test_completion_without_store_is_harmless():
    db = SessionLocal()
    tour = Tour(
        customer="Provenance-Test Storeless",
        calendar_week=42,
        date_from=date(2026, 10, 12),
        date_to=date(2026, 10, 16),
        status=TourStatus.assigned,
    )
    db.add(tour)
    db.flush()
    stop = Stop(tour_id=tour.id, row_index=0, customer="No Store", status="confirmed")
    db.add(stop)
    db.commit()
    tour_id, stop_id = tour.id, stop.id
    db.close()

    resp = client.post(f"/stops/{stop_id}/complete")
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    db.query(Stop).filter(Stop.tour_id == tour_id).delete()
    db.query(Tour).filter(Tour.id == tour_id).delete()
    db.commit()
    db.close()


def test_resolve_keep_store_dismisses_durably(world):
    _, stop_id, store_id = world

    resp = client.post(
        f"/stops/{stop_id}/resolve-address", json={"action": "keep_store"}
    )
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    stop = db.get(Stop, stop_id)
    store = db.get(Store, store_id)
    assert stop.address_review_resolved_at is not None
    assert stop.address_review_resolved_by == "Test Override Admin"
    # Claim and store both untouched: the flag stays (honest audit), only the
    # review row is settled.
    assert stop.claimed_street == "Falschestr. 9"
    assert stop.address_matches_store is False
    assert store.street == "Wahrestr. 1"
    db.close()


def test_resolve_use_claim_updates_the_store(world):
    _, stop_id, store_id = world

    resp = client.post(
        f"/stops/{stop_id}/resolve-address", json={"action": "use_claim"}
    )
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    stop = db.get(Stop, stop_id)
    store = db.get(Store, store_id)
    assert store.street == "Falschestr. 9"  # the plan was right
    assert store.address_provenance == AddressProvenance.verified
    assert store.verified_by == "Test Override Admin"
    assert stop.address_matches_store is True  # recomputed against the update
    assert stop.address_review_resolved_at is not None
    # The claim is still exactly what the paper printed.
    assert stop.claimed_street == "Falschestr. 9"
    db.close()

    # Nothing left to resolve now.
    again = client.post(
        f"/stops/{stop_id}/resolve-address", json={"action": "keep_store"}
    )
    assert again.status_code == 409


def test_resolve_requires_a_mismatch(world):
    _, stop_id, _ = world
    db = SessionLocal()
    db.get(Stop, stop_id).address_matches_store = True
    db.commit()
    db.close()

    resp = client.post(
        f"/stops/{stop_id}/resolve-address", json={"action": "keep_store"}
    )
    assert resp.status_code == 409
