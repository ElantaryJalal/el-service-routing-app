"""Learned per-store service times (P4).

Requires a reachable database with migrations applied; skipped when the DB is
unreachable. No network calls: OSRM is replaced by a fake matrix provider
(fixed 600 s drive between any two points).
"""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.store import Store
from app.models.tour import Tour
from app.services import service_times
from app.services.optimiser import _store_service_minutes
from app.services.service_times import recompute_service_times
from app.services.store_catalog import enrich_stop_from_store


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")

client = TestClient(app)


def _fake_matrix(coords):
    """600 s between any two distinct points, 0 on the diagonal."""
    n = len(coords)
    return [[0 if i == j else 600 for j in range(n)] for i in range(n)]


@pytest.fixture
def catalog_snapshot():
    """Recompute rewrites every store; restore the real catalog afterwards."""
    db = SessionLocal()
    snapshot = {
        s.id: (
            s.learned_service_minutes,
            s.service_time_samples,
            s.service_times_updated_at,
        )
        for s in db.query(Store)
    }
    db.close()

    yield

    db = SessionLocal()
    for store in db.query(Store):
        if store.id in snapshot:
            (
                store.learned_service_minutes,
                store.service_time_samples,
                store.service_times_updated_at,
            ) = snapshot[store.id]
    db.commit()
    db.close()


@pytest.fixture
def seeded(catalog_snapshot):
    """Two stores and three days of completion history.

    Day 1: B done 08:00 (seq 1), A done 09:10 (seq 2)
            -> A observes 4200 - 600 = 3600 s (60 min)
    Day 2: no-store stop done 08:00 (seq 1), A done 09:20 (seq 2),
            B done 10:30 (seq 3)
            -> A observes 4800 - 600 = 4200 s (70 min); B observes 60 min once
    Day 3: B done 08:00 (seq 1), A done 10:00 (seq *3*)
            -> sequence gap (an uncompleted stop between them): no observation

    Expected: A samples [60, 70] -> learned median 65; B has 1 sample, below
    MIN_SAMPLES -> learned stays null.
    """
    db = SessionLocal()
    store_a = Store(name="Testmarkt Lernzeit A", postal_code="99101", city="Teststadt")
    store_b = Store(name="Testmarkt Lernzeit B", postal_code="99102", city="Teststadt")
    tour = Tour(
        customer="Aldi Nord",
        calendar_week=27,
        date_from=date(2026, 6, 29),
        date_to=date(2026, 7, 3),
    )
    db.add_all([store_a, store_b, tour])
    db.flush()

    def stop(row, day, seq, store_id, hour, minute, lon):
        return Stop(
            tour_id=tour.id,
            store_id=store_id,
            row_index=row,
            assigned_day=day,
            sequence=seq,
            geom=f"SRID=4326;POINT({lon} 51.30)",
            completed_at=datetime(
                day.year, day.month, day.day, hour, minute, tzinfo=UTC
            ),
        )

    day1, day2, day3 = date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1)
    db.add_all(
        [
            stop(0, day1, 1, store_b.id, 8, 0, 12.30),
            stop(1, day1, 2, store_a.id, 9, 10, 12.35),
            stop(2, day2, 1, None, 8, 0, 12.40),
            stop(3, day2, 2, store_a.id, 9, 20, 12.45),
            stop(4, day2, 3, store_b.id, 10, 30, 12.50),
            stop(5, day3, 1, store_b.id, 8, 0, 12.55),
            stop(6, day3, 3, store_a.id, 10, 0, 12.60),
        ]
    )
    db.commit()
    ids = (store_a.id, store_b.id, tour.id)
    db.close()

    yield ids

    db = SessionLocal()
    db.query(Tour).filter(Tour.id == ids[2]).delete()  # cascades to the stops
    db.query(Store).filter(Store.id.in_(ids[:2])).delete()
    db.commit()
    db.close()


def test_recompute_learns_median_and_respects_min_samples(seeded):
    store_a_id, store_b_id, _ = seeded

    db = SessionLocal()
    results = {
        r.store_id: r for r in recompute_service_times(db, matrix_provider=_fake_matrix)
    }

    # A: two plausible observations (60, 70 min) -> median 65. The day-3 pair
    # is sequence-gapped and must not have contributed a third.
    assert results[store_a_id].samples == 2
    assert results[store_a_id].learned_service_minutes == 65

    # B: one observation only -> counted, but below the learning threshold.
    assert results[store_b_id].samples == 1
    assert results[store_b_id].learned_service_minutes is None

    store_a = db.get(Store, store_a_id)
    assert store_a.learned_service_minutes == 65
    assert store_a.service_time_samples == 2
    assert store_a.service_times_updated_at is not None
    db.close()


def test_recompute_endpoint_and_store_read(seeded, monkeypatch):
    store_a_id, _, _ = seeded
    monkeypatch.setattr(service_times, "_osrm_matrix", _fake_matrix)

    resp = client.post("/stores/service-times/recompute")
    assert resp.status_code == 200
    entry = next(r for r in resp.json() if r["store_id"] == store_a_id)
    assert entry["learned_service_minutes"] == 65
    assert entry["samples"] == 2

    body = client.get(f"/stores/{store_a_id}").json()
    assert body["learned_service_minutes"] == 65
    assert body["service_time_samples"] == 2
    assert body["service_times_updated_at"] is not None


def test_offline_sync_bursts_are_not_observations(seeded):
    """Completions stamped seconds apart (outbox sync) must be discarded."""
    store_a_id, _, tour_id = seeded

    db = SessionLocal()
    day = date(2026, 7, 2)
    base = datetime(2026, 7, 2, 16, 0, tzinfo=UTC)
    for seq, lon in [(1, 12.70), (2, 12.75)]:
        db.add(
            Stop(
                tour_id=tour_id,
                store_id=store_a_id,
                row_index=6 + seq,
                assigned_day=day,
                sequence=seq,
                geom=f"SRID=4326;POINT({lon} 51.30)",
                completed_at=base.replace(second=seq * 15),
            )
        )
    db.commit()

    results = {
        r.store_id: r for r in recompute_service_times(db, matrix_provider=_fake_matrix)
    }
    assert results[store_a_id].samples == 2  # unchanged: the burst pair is out
    db.close()


def test_enrichment_prefers_learned_over_default(seeded):
    store_a_id, _, _ = seeded
    db = SessionLocal()
    store = db.get(Store, store_a_id)
    store.learned_service_minutes = 65
    store.default_service_minutes = 45

    blank = Stop(tour_id=0, row_index=0)
    enrich_stop_from_store(blank, store)
    assert blank.service_minutes == 65

    # An explicit value on the stop (plan / crew) is never overridden.
    manual = Stop(tour_id=0, row_index=1, service_minutes=30)
    enrich_stop_from_store(manual, store)
    assert manual.service_minutes == 30

    db.rollback()
    db.close()


def test_optimiser_store_fallback_minutes(seeded):
    store_a_id, store_b_id, _ = seeded
    db = SessionLocal()
    store_a = db.get(Store, store_a_id)
    store_b = db.get(Store, store_b_id)
    store_a.learned_service_minutes = 65
    store_a.default_service_minutes = 45
    store_b.learned_service_minutes = None
    store_b.default_service_minutes = 50
    db.flush()

    stops = [
        Stop(tour_id=0, row_index=0, store_id=store_a_id),
        Stop(tour_id=0, row_index=1, store_id=store_b_id),
        Stop(tour_id=0, row_index=2, store_id=None),
    ]
    fallback = _store_service_minutes(db, stops)
    assert fallback[store_a_id] == 65  # learned wins
    assert fallback[store_b_id] == 50  # default when nothing learned
    assert None not in fallback

    db.rollback()
    db.close()
