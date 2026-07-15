"""GET /reports/overview: week-scoped completion KPIs and role access.

Acceptance: a manager reads this-week completion KPIs; a worker gets 403.
Uses real tokens (USE_REAL_AUTH) because the endpoint is purely role-gated.

Requires a reachable database with migrations applied; skipped otherwise.
"""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.tour import Tour, TourStatus
from app.models.user import Role, User
from app.security import hash_password

USE_REAL_AUTH = True

TEST_DOMAIN = "reportstest.elservice.de"
PASSWORD = "reports-pass-123"

# A week far away from any real/dev data so the aggregates are deterministic.
WEEK_FROM = date(2027, 3, 1)
WEEK_TO = date(2027, 3, 7)


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
    """A manager and a worker; one in_progress tour with three stops (one on
    time, one late, one outstanding) and one draft tour in the test week."""
    db = SessionLocal()

    users = {}
    for key, role in (("manager", Role.manager), ("worker", Role.worker)):
        user = User(
            email=f"{key}@{TEST_DOMAIN}",
            password_hash=hash_password(PASSWORD),
            name=key.title(),
            role=role,
        )
        db.add(user)
        users[key] = user
    db.flush()

    work_tour = Tour(
        customer="Aldi Nord",
        calendar_week=9,
        date_from=WEEK_FROM,
        date_to=date(2027, 3, 5),
        status=TourStatus.in_progress,
    )
    draft_tour = Tour(
        customer="Aldi Nord",
        calendar_week=9,
        date_from=WEEK_FROM,
        date_to=date(2027, 3, 5),
        status=TourStatus.draft,
    )
    db.add_all([work_tour, draft_tour])
    db.flush()

    day1 = WEEK_FROM
    stops = [
        # Completed 10 min after ETA — on time within the 30 min tolerance.
        Stop(
            tour_id=work_tour.id,
            row_index=0,
            customer="Markt Punctual",
            city="Leipzig",
            status="done",
            assigned_day=day1,
            sequence=1,
            eta=datetime(2027, 3, 1, 9, 0, tzinfo=UTC),
            completed_at=datetime(2027, 3, 1, 9, 10, tzinfo=UTC),
        ),
        # Completed 60 min after ETA — late.
        Stop(
            tour_id=work_tour.id,
            row_index=1,
            customer="Markt Late",
            city="Leipzig",
            status="done",
            assigned_day=day1,
            sequence=2,
            eta=datetime(2027, 3, 1, 10, 0, tzinfo=UTC),
            completed_at=datetime(2027, 3, 1, 11, 0, tzinfo=UTC),
        ),
        # Still outstanding.
        Stop(
            tour_id=work_tour.id,
            row_index=2,
            customer="Markt Outstanding",
            city="Taucha",
            status="confirmed",
            assigned_day=date(2027, 3, 2),
            sequence=1,
            eta=datetime(2027, 3, 2, 9, 0, tzinfo=UTC),
        ),
        # Draft-tour stop: excluded from every stop KPI.
        Stop(
            tour_id=draft_tour.id,
            row_index=0,
            customer="Markt Draft",
            status="unconfirmed",
        ),
    ]
    db.add_all(stops)
    db.commit()

    ids = {
        "tours": [work_tour.id, draft_tour.id],
        "outstanding_stop": stops[2].id,
    }
    db.close()

    yield ids

    db = SessionLocal()
    db.query(Stop).filter(Stop.tour_id.in_(ids["tours"])).delete(
        synchronize_session=False
    )
    db.query(Tour).filter(Tour.id.in_(ids["tours"])).delete(synchronize_session=False)
    db.query(User).filter(User.email.like(f"%@{TEST_DOMAIN}")).delete(
        synchronize_session=False
    )
    db.commit()
    db.close()


def _token(key: str) -> str:
    resp = client.post(
        "/auth/login", json={"email": f"{key}@{TEST_DOMAIN}", "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _overview(token: str, **params) -> dict:
    resp = client.get("/reports/overview", headers=_auth(token), params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_manager_reads_week_kpis(world):
    report = _overview(
        _token("manager"), date_from=str(WEEK_FROM), date_to=str(WEEK_TO)
    )

    assert report["tours"]["total"] == 2
    assert report["tours"]["draft"] == 1
    assert report["tours"]["in_progress"] == 1

    # Draft-tour stops are not part of the workload.
    assert report["stops_planned"] == 3
    assert report["stops_completed"] == 2

    on_time = report["on_time"]
    assert on_time["sample_count"] == 2
    assert on_time["on_time_count"] == 1
    assert on_time["on_time_rate"] == 0.5
    assert on_time["average_delta_minutes"] == 35.0
    assert on_time["tolerance_minutes"] == 30

    outstanding = report["outstanding"]
    assert [s["stop_id"] for s in outstanding] == [world["outstanding_stop"]]
    assert outstanding[0]["customer"] == "Markt Outstanding"

    by_day = {d["day"]: d for d in report["days"]}
    assert len(report["days"]) == 7
    assert by_day["2027-03-01"]["planned"] == 2
    assert by_day["2027-03-01"]["completed"] == 2
    assert by_day["2027-03-02"]["planned"] == 1
    assert by_day["2027-03-02"]["completed"] == 0


def test_tolerance_changes_on_time_rate(world):
    report = _overview(
        _token("manager"),
        date_from=str(WEEK_FROM),
        date_to=str(WEEK_TO),
        tolerance_minutes=90,
    )
    assert report["on_time"]["on_time_rate"] == 1.0


def test_defaults_to_current_week(world):
    report = _overview(_token("manager"))
    monday = date.fromisoformat(report["date_from"])
    assert monday.weekday() == 0
    assert (date.fromisoformat(report["date_to"]) - monday).days == 6


def test_half_open_range_rejected(world):
    resp = client.get(
        "/reports/overview",
        headers=_auth(_token("manager")),
        params={"date_from": str(WEEK_FROM)},
    )
    assert resp.status_code == 422


def test_worker_cannot_read_reports(world):
    resp = client.get("/reports/overview", headers=_auth(_token("worker")))
    assert resp.status_code == 403
