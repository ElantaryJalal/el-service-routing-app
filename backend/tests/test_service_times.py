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
from app.models.service_record import (
    MeasurementMethod,
    ServiceRecord,
    task_signature,
)
from app.models.stop import StartSource, Stop
from app.models.store import Store
from app.models.task import Task
from app.models.tour import Tour
from app.services import service_times
from app.services.optimiser import (
    _profile_service_minutes,
    _store_service_minutes,
    service_estimates,
)
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
    "is_demo",
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

    Coordinates live on the stores (0012) — drive legs are measured between
    store geometries, so every anchoring stop needs a store-linked location.

    Day 1: B done 08:00 (seq 1), A done 09:10 (seq 2)
            -> A observes 4200 - 600 = 3600 s (60 min)
    Day 2: anchor-store stop done 08:00 (seq 1), A done 09:20 (seq 2),
            B done 10:30 (seq 3)
            -> A observes 4800 - 600 = 4200 s (70 min); B observes 60 min once
    Day 3: B done 08:00 (seq 1), A done 10:00 (seq *3*)
            -> sequence gap (an uncompleted stop between them): no observation

    Expected: A samples [60, 70] -> learned median 65; B has 1 sample, below
    MIN_SAMPLES -> learned stays null.
    """
    db = SessionLocal()
    store_a = Store(
        name="Testmarkt Lernzeit A",
        postal_code="99101",
        city="Teststadt",
        geom="SRID=4326;POINT(12.35 51.30)",
    )
    store_b = Store(
        name="Testmarkt Lernzeit B",
        postal_code="99102",
        city="Teststadt",
        geom="SRID=4326;POINT(12.50 51.30)",
    )
    anchor = Store(
        name="Testmarkt Lernzeit Anker",
        postal_code="99109",
        city="Teststadt",
        geom="SRID=4326;POINT(12.40 51.30)",
    )
    tour = Tour(
        customer="Aldi Nord",
        calendar_week=27,
        date_from=date(2026, 6, 29),
        date_to=date(2026, 7, 3),
    )
    db.add_all([store_a, store_b, anchor, tour])
    db.flush()

    def stop(row, day, seq, store_id, hour, minute):
        return Stop(
            tour_id=tour.id,
            store_id=store_id,
            row_index=row,
            assigned_day=day,
            sequence=seq,
            completed_at=datetime(
                day.year, day.month, day.day, hour, minute, tzinfo=UTC
            ),
        )

    day1, day2, day3 = date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1)
    db.add_all(
        [
            stop(0, day1, 1, store_b.id, 8, 0),
            stop(1, day1, 2, store_a.id, 9, 10),
            stop(2, day2, 1, anchor.id, 8, 0),
            stop(3, day2, 2, store_a.id, 9, 20),
            stop(4, day2, 3, store_b.id, 10, 30),
            stop(5, day3, 1, store_b.id, 8, 0),
            stop(6, day3, 3, store_a.id, 10, 0),
        ]
    )
    db.commit()
    ids = (store_a.id, store_b.id, tour.id, anchor.id)
    db.close()

    yield ids[:3]

    db = SessionLocal()
    db.query(Tour).filter(Tour.id == ids[2]).delete()  # cascades to the stops
    db.query(Store).filter(Store.id.in_([ids[0], ids[1], ids[3]])).delete()
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


def test_recompute_carries_stop_is_demo(seeded):
    """A rebuild must never launder demo history into real-looking ledger
    rows (this happened once: a recompute through a pre-flag server washed
    out the migration's backfill)."""
    store_a_id, store_b_id, tour_id = seeded

    db = SessionLocal()
    db.query(Stop).filter(Stop.tour_id == tour_id).update({"is_demo": True})
    db.commit()

    recompute_service_times(db, matrix_provider=_fake_matrix)
    records = (
        db.query(ServiceRecord)
        .filter(ServiceRecord.store_id.in_([store_a_id, store_b_id]))
        .all()
    )
    assert records
    assert all(r.is_demo for r in records)
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
    for seq in (1, 2):
        db.add(
            Stop(
                tour_id=tour_id,
                store_id=store_a_id,
                row_index=6 + seq,
                assigned_day=day,
                sequence=seq,
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
    store = Store(
        name="Testmarkt Lernzeit C",
        postal_code="99103",
        city="Teststadt",
        geom="SRID=4326;POINT(12.25 51.30)",
    )
    anchor_store = Store(
        name="Testmarkt Lernzeit C-Anker",
        postal_code="99108",
        city="Teststadt",
        geom="SRID=4326;POINT(12.20 51.30)",
    )
    tour = Tour(
        customer="Aldi Nord",
        calendar_week=28,
        date_from=date(2026, 7, 6),
        date_to=date(2026, 7, 10),
        employee="Team Nord",
    )
    db.add_all([store, anchor_store, tour])
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
            store_id=anchor_store.id,
            row_index=row * 2,
            assigned_day=day,
            sequence=1,
            completed_at=datetime(day.year, day.month, day.day, 8, 0, tzinfo=UTC),
        )
        visit = Stop(
            tour_id=tour.id,
            store_id=store.id,
            row_index=row * 2 + 1,
            assigned_day=day,
            sequence=2,
            completed_at=datetime(day.year, day.month, day.day, 8, 0, tzinfo=UTC)
            + timedelta(minutes=minutes),
        )
        db.add_all([anchor, visit])
        db.flush()
        db.add(Task(stop_id=visit.id, task_type=label, raw_label=label))
    db.commit()
    ids = (store.id, tour.id, anchor_store.id)
    db.close()

    yield ids[:2]

    db = SessionLocal()
    db.query(Tour).filter(Tour.id == ids[1]).delete()  # cascades to the stops
    db.query(Store).filter(Store.id.in_([ids[0], ids[2]])).delete()
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


def test_service_estimates_report_minutes_and_source(seeded):
    """The stop card's estimate resolves to a number AND names its origin, so
    a plain default is never passed off as a task-linked measurement."""
    store_a_id, store_b_id, tour_id = seeded
    db = SessionLocal()
    store_a = db.get(Store, store_a_id)
    store_b = db.get(Store, store_b_id)
    store_a.learned_service_minutes = 65
    store_a.default_service_minutes = 45
    store_b.learned_service_minutes = None
    store_b.default_service_minutes = 50
    db.flush()

    # A learned per-task profile for store_a + the {EKW, Körbe} task set: two
    # samples (>= MIN_SAMPLES) so the median 55 becomes a usable estimate.
    signature = task_signature(["EKW", "Körbe"])
    anchors = db.query(Stop).filter(Stop.store_id == store_a_id).limit(2).all()
    for anchor in anchors:
        db.add(
            ServiceRecord(
                stop_id=anchor.id,
                store_id=store_a_id,
                tour_id=tour_id,
                task_signature=signature,
                duration_minutes=55,
            )
        )
    db.flush()

    def make(store_id, tasks, service_minutes=None):
        stop = Stop(
            tour_id=tour_id,
            row_index=99,
            store_id=store_id,
            service_minutes=service_minutes,
        )
        stop.tasks = [Task(task_type=t) for t in tasks]
        db.add(stop)
        return stop

    override = make(store_a_id, ["EKW", "Körbe"], service_minutes=90)
    profile = make(store_a_id, ["EKW", "Körbe"])
    store_learned = make(store_a_id, [])  # empty task set: no profile match
    store_default = make(store_b_id, [])  # nothing learned -> hand-set default
    global_default = make(None, [])  # no store at all -> global default
    db.flush()  # assign ids used as the result keys

    est = service_estimates(
        db, [override, profile, store_learned, store_default, global_default]
    )
    assert (est[override.id].minutes, est[override.id].source) == (90, "override")
    assert (est[profile.id].minutes, est[profile.id].source) == (55, "profile")
    assert (est[store_learned.id].minutes, est[store_learned.id].source) == (
        65,
        "store_learned",
    )
    assert (est[store_default.id].minutes, est[store_default.id].source) == (
        50,
        "store_default",
    )
    # A real number even with no data anywhere, honestly flagged as a default.
    assert est[global_default.id].source == "default"
    assert est[global_default.id].minutes > 0

    db.rollback()
    db.close()


@pytest.fixture
def direct_world(catalog_snapshot):
    """Stores exercising the DIRECT vs DERIVED ledger paths. Each service sits
    on its own (tour, day) so nothing pairs across stores by accident."""
    db = SessionLocal()
    store_d = Store(
        name="Directmarkt D",
        postal_code="99201",
        city="Teststadt",
        geom="SRID=4326;POINT(12.60 51.30)",
    )
    store_e = Store(
        name="Directmarkt E",
        postal_code="99202",
        city="Teststadt",
        geom="SRID=4326;POINT(12.62 51.30)",
    )
    anchor = Store(
        name="Directmarkt Anker",
        postal_code="99209",
        city="Teststadt",
        geom="SRID=4326;POINT(12.61 51.30)",
    )
    store_f = Store(
        name="Directmarkt F",
        postal_code="99203",
        city="Teststadt",
        geom="SRID=4326;POINT(12.64 51.30)",
    )
    tour = Tour(
        customer="Aldi Nord",
        calendar_week=30,
        date_from=date(2026, 7, 20),
        date_to=date(2026, 7, 31),
    )
    db.add_all([store_d, store_e, anchor, store_f, tour])
    db.flush()

    def at(d, h, m):
        return datetime(d.year, d.month, d.day, h, m, tzinfo=UTC)

    def direct(store_id, day, minutes, row):
        return Stop(
            tour_id=tour.id,
            store_id=store_id,
            row_index=row,
            assigned_day=day,
            sequence=1,
            started_at=at(day, 8, 0),
            completed_at=at(day, 8, 0) + timedelta(minutes=minutes),
            start_source=StartSource.manual,
        )

    d = [date(2026, 7, day) for day in range(20, 32)]  # 12 distinct days
    stops = [
        direct(store_d.id, d[0], 65, 0),  # DIRECT 65 min (no drive term)
        direct(store_e.id, d[1], 60, 1),  # DIRECT 60
        direct(store_e.id, d[2], 60, 2),  # DIRECT 60  -> enough to prefer
        direct(store_f.id, d[6], 24 * 60, 20),  # implausible: open 24h
        direct(store_f.id, d[7], 5, 21),  # implausible: 5 min
    ]
    # store_e also has two DERIVED visits (anchor seq1 + E seq2, no start):
    # gap 200 min - 10 min drive = 190 min each.
    for i, day in enumerate((d[3], d[4])):
        stops.append(
            Stop(
                tour_id=tour.id,
                store_id=anchor.id,
                row_index=30 + i * 2,
                assigned_day=day,
                sequence=1,
                completed_at=at(day, 8, 0),
            )
        )
        stops.append(
            Stop(
                tour_id=tour.id,
                store_id=store_e.id,
                row_index=31 + i * 2,
                assigned_day=day,
                sequence=2,
                completed_at=at(day, 8, 0) + timedelta(minutes=200),
            )
        )
    db.add_all(stops)
    db.commit()
    ids = {
        "d": store_d.id,
        "e": store_e.id,
        "f": store_f.id,
        "anchor": anchor.id,
        "tour": tour.id,
    }
    db.close()

    yield ids

    db = SessionLocal()
    db.query(Tour).filter(Tour.id == ids["tour"]).delete()
    db.query(Store).filter(
        Store.id.in_([ids["d"], ids["e"], ids["f"], ids["anchor"]])
    ).delete()
    db.commit()
    db.close()


def test_direct_observation_is_done_minus_start_no_drive(direct_world):
    """A stop with started_at yields completed_at - started_at exactly — no
    drive subtraction, no neighbouring stop needed."""
    db = SessionLocal()
    recompute_service_times(db, matrix_provider=_fake_matrix)
    records = db.query(ServiceRecord).filter_by(store_id=direct_world["d"]).all()
    assert len(records) == 1
    rec = records[0]
    assert rec.measurement_method == MeasurementMethod.direct
    assert rec.duration_minutes == 65  # 65, not 65 - drive
    db.close()


def test_derived_still_produced_without_start_and_is_tagged(direct_world):
    """A stop with no started_at still gets a derived record (adjacency +
    drive subtraction), distinguishable by measurement_method."""
    db = SessionLocal()
    recompute_service_times(db, matrix_provider=_fake_matrix)
    records = db.query(ServiceRecord).filter_by(store_id=direct_world["e"]).all()
    by_method = {}
    for r in records:
        by_method.setdefault(r.measurement_method, []).append(r.duration_minutes)
    assert sorted(by_method[MeasurementMethod.direct]) == [60, 60]
    assert sorted(by_method[MeasurementMethod.derived]) == [190, 190]
    db.close()


def test_direct_preferred_over_derived_when_enough(direct_world):
    """With enough direct records the learned estimate ignores the derived
    ones, though the ledger keeps every row."""
    db = SessionLocal()
    results = {
        r.store_id: r for r in recompute_service_times(db, matrix_provider=_fake_matrix)
    }
    entry = results[direct_world["e"]]
    # median of the two DIRECT 60s, not median(60, 60, 190, 190) = 125.
    assert entry.learned_service_minutes == 60
    assert entry.samples == 2  # the direct pair backs the estimate
    # ...but all four observations are still in the ledger.
    total = db.query(ServiceRecord).filter_by(store_id=direct_world["e"]).count()
    assert total == 4
    store_e = db.get(Store, direct_world["e"])
    assert store_e.learned_service_minutes == 60
    db.close()


def test_implausible_direct_durations_rejected(direct_world):
    """A forgotten Start (open for hours) or a mis-tap (seconds) never enters
    the ledger, same bounds as the derived path."""
    db = SessionLocal()
    results = {
        r.store_id: r for r in recompute_service_times(db, matrix_provider=_fake_matrix)
    }
    assert results[direct_world["f"]].samples == 0
    assert results[direct_world["f"]].learned_service_minutes is None
    assert db.query(ServiceRecord).filter_by(store_id=direct_world["f"]).count() == 0
    db.close()
