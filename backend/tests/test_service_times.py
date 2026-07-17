"""Learned per-store service times (P4).

Requires a reachable database with migrations applied; skipped when the DB is
unreachable. No network calls: OSRM is replaced by a fake matrix provider
(fixed 600 s drive between any two points).
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models.service_record import ServiceRecord, task_signature
from app.models.stop import Stop
from app.models.store import Store
from app.models.task import Task
from app.models.tour import Tour
from app.services import service_times
from app.services.optimiser import _profile_service_minutes, _store_service_minutes
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


_LEDGER_FIELDS = (
    "stop_id",
    "store_id",
    "tour_id",
    "user_id",
    "team",
    "serviced_on",
    "task_signature",
    "tasks_label",
    "duration_minutes",
)


@pytest.fixture
def catalog_snapshot():
    """Recompute rewrites every store (and rebuilds the whole service
    ledger); restore the real catalog afterwards."""
    db = SessionLocal()
    snapshot = {
        s.id: (
            s.learned_service_minutes,
            s.service_time_samples,
            s.service_times_updated_at,
        )
        for s in db.query(Store)
    }
    ledger = [
        {f: getattr(r, f) for f in _LEDGER_FIELDS} for r in db.query(ServiceRecord)
    ]
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
    db.query(ServiceRecord).delete()
    surviving_stops = {row[0] for row in db.query(Stop.id)}
    for record in ledger:
        if record["stop_id"] in surviving_stops:
            db.add(ServiceRecord(**record))
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


@pytest.fixture
def two_profiles(catalog_snapshot):
    """One store, two service profiles across four days.

    Each day: an anchor stop (no store) done 08:00 seq 1, then store C seq 2.
    Days 1-2 are EKW visits (60, 70 min); days 3-4 Grundreinigung (170, 190).
    Expected: profile 'ekw' learns 65, 'grundreinigung' learns 180, and the
    store-wide median (the unmatched-profile fallback) is 120.
    """
    db = SessionLocal()
    store = Store(name="Testmarkt Lernzeit C", postal_code="99103", city="Teststadt")
    tour = Tour(
        customer="Aldi Nord",
        calendar_week=28,
        date_from=date(2026, 7, 6),
        date_to=date(2026, 7, 10),
        employee="Team Nord",
    )
    db.add_all([store, tour])
    db.flush()

    visits = [  # (day, service task label, completion minutes after 08:00)
        (date(2026, 7, 6), "EKW", 70),  # 4200 s gap - 600 drive = 60 min
        (date(2026, 7, 7), "EKW", 80),  # 70 min
        (date(2026, 7, 8), "Grundreinigung", 180),  # 170 min
        (date(2026, 7, 9), "Grundreinigung", 200),  # 190 min
    ]
    for row, (day, label, minutes) in enumerate(visits):
        anchor = Stop(
            tour_id=tour.id,
            row_index=row * 2,
            assigned_day=day,
            sequence=1,
            geom="SRID=4326;POINT(12.20 51.30)",
            completed_at=datetime(day.year, day.month, day.day, 8, 0, tzinfo=UTC),
        )
        visit = Stop(
            tour_id=tour.id,
            store_id=store.id,
            row_index=row * 2 + 1,
            assigned_day=day,
            sequence=2,
            geom="SRID=4326;POINT(12.25 51.30)",
            completed_at=datetime(day.year, day.month, day.day, 8, 0, tzinfo=UTC)
            + timedelta(minutes=minutes),
        )
        db.add_all([anchor, visit])
        db.flush()
        db.add(Task(stop_id=visit.id, task_type=label, raw_label=label))
    db.commit()
    ids = (store.id, tour.id)
    db.close()

    yield ids

    db = SessionLocal()
    db.query(Tour).filter(Tour.id == ids[1]).delete()  # cascades to the stops
    db.query(Store).filter(Store.id == ids[0]).delete()  # cascades to profiles
    db.commit()
    db.close()


def test_profiles_learn_separately_per_service(two_profiles):
    store_id, _ = two_profiles

    db = SessionLocal()
    results = {
        r.store_id: r for r in recompute_service_times(db, matrix_provider=_fake_matrix)
    }

    entry = results[store_id]
    assert entry.samples == 4
    assert entry.learned_service_minutes == 120  # median across both services

    by_signature = {p.task_signature: p for p in entry.by_service}
    assert by_signature["ekw"].learned_minutes == 65
    assert by_signature["ekw"].samples == 2
    assert by_signature["ekw"].tasks_label == "EKW"
    assert by_signature["grundreinigung"].learned_minutes == 180

    # The ledger holds one row per performed service, with the responsible
    # team and the derived duration — the estimates are its aggregates.
    records = db.query(ServiceRecord).filter_by(store_id=store_id).all()
    assert sorted(r.duration_minutes for r in records) == [60, 70, 170, 190]
    assert {r.team for r in records} == {"Team Nord"}
    assert {r.task_signature for r in records} == {"ekw", "grundreinigung"}
    assert all(r.serviced_on is not None and r.tour_id is not None for r in records)
    db.close()


def test_enrichment_matches_the_rows_service_profile(two_profiles):
    store_id, _ = two_profiles
    db = SessionLocal()
    recompute_service_times(db, matrix_provider=_fake_matrix)
    store = db.get(Store, store_id)
    store.default_service_minutes = 45

    # A row whose tasks match a learned profile gets that profile's time...
    ekw_stop = Stop(tour_id=0, row_index=0)
    ekw_stop.tasks.append(Task(task_type="EKW", raw_label="EKW"))
    enrich_stop_from_store(ekw_stop, store)
    assert ekw_stop.service_minutes == 65

    # ...a never-seen profile falls back to the store-wide median...
    other = Stop(tour_id=0, row_index=1)
    other.tasks.append(Task(task_type="Sonderleistung", raw_label="Sonderleistung"))
    enrich_stop_from_store(other, store)
    assert other.service_minutes == 120

    # ...and an explicit value on the row is never overridden.
    manual = Stop(tour_id=0, row_index=2, service_minutes=30)
    manual.tasks.append(Task(task_type="EKW", raw_label="EKW"))
    enrich_stop_from_store(manual, store)
    assert manual.service_minutes == 30

    db.rollback()
    db.close()


def test_optimiser_profile_fallback(two_profiles):
    store_id, _ = two_profiles
    db = SessionLocal()
    recompute_service_times(db, matrix_provider=_fake_matrix)

    stops = [Stop(tour_id=0, row_index=0, store_id=store_id)]
    lookup = _profile_service_minutes(db, stops)
    assert lookup[(store_id, "ekw")] == 65
    assert lookup[(store_id, "grundreinigung")] == 180
    assert task_signature(["Grundreinigung"]) == "grundreinigung"

    db.rollback()
    db.close()


def test_store_read_includes_service_profiles(two_profiles):
    store_id, _ = two_profiles
    db = SessionLocal()
    recompute_service_times(db, matrix_provider=_fake_matrix)
    db.close()

    body = client.get(f"/stores/{store_id}").json()
    profiles = {p["task_signature"]: p for p in body["service_times"]}
    assert profiles["ekw"]["learned_minutes"] == 65
    assert profiles["ekw"]["tasks_label"] == "EKW"
    assert profiles["grundreinigung"]["learned_minutes"] == 180
    assert body["learned_service_minutes"] == 120
    assert body["total_service_minutes"] == 60 + 70 + 170 + 190
    assert body["services_recorded"] == 4


def test_store_visits_carry_the_performed_service(two_profiles):
    store_id, _ = two_profiles
    db = SessionLocal()
    recompute_service_times(db, matrix_provider=_fake_matrix)
    db.close()

    visits = client.get(f"/stores/{store_id}/visits").json()
    assert len(visits) == 4
    assert sorted(v["duration_minutes"] for v in visits) == [60, 70, 170, 190]
    assert {v["employee"] for v in visits} == {"Team Nord"}
    assert {v["tasks"] for v in visits} == {"EKW", "Grundreinigung"}


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
