"""Worker "add another stop": pull a feasible later-day stop into today.

Service-level tests use a fake 1-D OSRM (drive time = |Δlongitude|) and a fixed
`now`, so ranking and feasibility are deterministic. One endpoint test covers
auth/plumbing against the real running OSRM.
"""

from datetime import date, datetime, time

import pytest
from fastapi.testclient import TestClient
from geoalchemy2.elements import WKTElement

from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.store import GeomProvenance, Store
from app.models.tour import Tour, TourStatus
from app.models.user import Role, User
from app.security import hash_password
from app.services.pull_forward import pull_candidates, pull_into_today

USE_REAL_AUTH = True

TAG = "PULLTEST"
DOMAIN = "pulltest.elservice.de"
PASSWORD = "pull-pass-123"
TODAY = date(2026, 7, 14)  # a Tuesday inside the tour week


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")
client = TestClient(app)


class LineOSRM:
    """Drive time = |Δlongitude| * SCALE seconds — a clean 1-D metric so drive
    ranking and nearest-neighbour ordering are deterministic in tests."""

    SCALE = 6000  # 0.1° of longitude == 600 s == 10 min

    def duration_matrix(self, coords, *, profile="driving"):
        # round() clears binary-float dust (12.1 - 12.0 != 0.1 exactly).
        return [[round(abs(a[0] - b[0]) * self.SCALE) for b in coords] for a in coords]


def _store(db, lon, lat, *, closing=time(18, 0)):
    s = Store(
        name=f"{TAG} Store {lon}",
        city="Leipzig",
        geom=WKTElement(f"POINT({lon} {lat})", srid=4326),
        geom_provenance=GeomProvenance.geocoded,
        opening_time=time(8, 0),
        closing_time=closing,
    )
    db.add(s)
    db.flush()
    return s


def _stop(db, tour, store, day, *, completed=None, service=60):
    st = Stop(
        tour_id=tour.id,
        store_id=store.id,
        row_index=0,
        customer=store.name,
        status="confirmed",
        assigned_day=day,
        service_minutes=service,
        completed_at=completed,
    )
    db.add(st)
    db.flush()
    return st


@pytest.fixture
def world():
    """A worker's tour with one completed stop today and later-day stops:
    A (near), B (further), C (closes 09:00 — unreachable in time)."""
    db = SessionLocal()
    worker = User(
        email=f"worker@{DOMAIN}",
        password_hash=hash_password(PASSWORD),
        name="Pull Worker",
        role=Role.worker,
    )
    manager = User(
        email=f"manager@{DOMAIN}",
        password_hash=hash_password(PASSWORD),
        name="Pull Manager",
        role=Role.manager,
    )
    db.add_all([worker, manager])
    db.flush()

    tour = Tour(
        customer=TAG,
        calendar_week=29,
        date_from=date(2026, 7, 13),
        date_to=date(2026, 7, 17),
        status=TourStatus.assigned,
        assigned_user_id=worker.id,
    )
    db.add(tour)
    db.flush()

    done = _stop(db, tour, _store(db, 12.05, 51.0), TODAY, completed=datetime(2026, 7, 14, 9, 0))
    done.eta = datetime(2026, 7, 14, 9, 0)
    a = _stop(db, tour, _store(db, 12.1, 51.0), date(2026, 7, 15))
    b = _stop(db, tour, _store(db, 12.2, 51.0), date(2026, 7, 15))
    c = _stop(db, tour, _store(db, 12.9, 51.0, closing=time(9, 0)), date(2026, 7, 16))
    db.commit()

    ids = {
        "worker": worker.id,
        "tour": tour.id,
        "done": done.id,
        "a": a.id,
        "b": b.id,
        "c": c.id,
    }
    db.close()
    yield ids

    db = SessionLocal()
    db.query(Stop).filter(Stop.tour_id == ids["tour"]).delete(synchronize_session=False)
    db.query(Tour).filter(Tour.id == ids["tour"]).delete(synchronize_session=False)
    db.query(Store).filter(Store.name.like(f"{TAG}%")).delete(synchronize_session=False)
    db.query(User).filter(User.email.like(f"%@{DOMAIN}")).delete(synchronize_session=False)
    db.commit()
    db.close()


def test_ranks_by_drive_time_and_excludes_unreachable(world):
    db = SessionLocal()
    tour = db.get(Tour, world["tour"])
    # Worker at lon 12.0; A is 10 min, B is 20 min, C is 90 min but closes 09:00.
    got = pull_candidates(
        db, tour, from_lat=51.0, from_lng=12.0, day=TODAY,
        now=datetime(2026, 7, 14, 10, 0), osrm=LineOSRM(),
    )
    db.close()
    ids = [c.stop_id for c in got]
    assert ids == [world["a"], world["b"]]  # ranked by real drive time
    assert world["c"] not in ids  # closes before the worker could arrive
    a = got[0]
    assert a.drive_seconds == 600 and a.projected_arrival == time(10, 10)
    assert a.service_minutes == 60


def test_working_window_excludes_late_finishers(world):
    db = SessionLocal()
    tour = db.get(Tour, world["tour"])
    # 18:30 now: A is 10 min away, service 60 -> finishes 19:40, past 19:00 end.
    got = pull_candidates(
        db, tour, from_lat=51.0, from_lng=12.0, day=TODAY,
        now=datetime(2026, 7, 14, 18, 30), osrm=LineOSRM(),
    )
    db.close()
    assert got == []  # nothing can be finished within the working day


def test_pull_into_today_reassigns_and_resequences(world):
    db = SessionLocal()
    tour = db.get(Tour, world["tour"])
    stop = db.get(Stop, world["a"])
    pull_into_today(
        db, tour, stop, TODAY, now=datetime(2026, 7, 14, 10, 0), osrm=LineOSRM()
    )
    db.expire_all()
    a = db.get(Stop, world["a"])
    done = db.get(Stop, world["done"])
    assert a.assigned_day == TODAY  # moved into today
    assert a.sequence == 2 and done.sequence == 1  # after the completed stop
    assert a.eta is not None  # re-timed from the last position (09:00 + 5 min)
    assert a.eta.time() == time(9, 5)
    # B stays on its original day.
    assert db.get(Stop, world["b"]).assigned_day == date(2026, 7, 15)

    # Idempotent: a retry leaves it on today without error.
    pull_into_today(
        db, tour, a, TODAY, now=datetime(2026, 7, 14, 10, 0), osrm=LineOSRM()
    )
    db.expire_all()
    assert db.get(Stop, world["a"]).assigned_day == TODAY
    db.close()


def _login(email):
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_endpoint_auth_and_plumbing(world):
    # Worker (own tour) can query candidates against the real OSRM engine.
    worker = _login(f"worker@{DOMAIN}")
    resp = client.get(
        f"/tours/{world['tour']}/pull-candidates",
        params={"from_lat": 51.34, "from_lng": 12.37, "day": TODAY.isoformat()},
        headers=worker,
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)

    # A manager is read-only on field work -> 403.
    manager = _login(f"manager@{DOMAIN}")
    resp = client.get(
        f"/tours/{world['tour']}/pull-candidates",
        params={"from_lat": 51.34, "from_lng": 12.37, "day": TODAY.isoformat()},
        headers=manager,
    )
    assert resp.status_code == 403
