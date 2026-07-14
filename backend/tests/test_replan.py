"""Mid-week re-planning and manual plan edits.

Same footing as test_optimise.py: needs the database and a running Vroom; the
OSRM matrix is injected (zero travel), so no routing network calls. The manual
plan edits and GET /tours/{id}/plan never touch the solver at all.
"""

from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from geoalchemy2.elements import WKTElement

from app.config import settings
from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.tour import DateMode, Tour, TourStatus
from app.routing.vroom import VroomClient
from app.services.optimiser import (
    REASON_NO_DAYS,
    REASON_REMOVED_MANUALLY,
    OptimiseConfig,
    _last_completed_coord,
    current_plan,
    move_stop,
    optimise_tour,
)

MONDAY = date(2026, 6, 29)
WEDNESDAY = MONDAY + timedelta(days=2)
FRIDAY = date(2026, 7, 3)

CONFIG = OptimiseConfig(
    working_start=time(7, 0),
    working_end=time(19, 0),
    default_service_minutes=60,
    skip_weekdays={6},
    near_limit_seconds=1800,
)


def _zero_matrix(coords):
    n = len(coords)
    return [[0] * n for _ in range(n)]


def _db_ok() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


def _vroom_ok() -> bool:
    try:
        httpx.get(settings.vroom_url, timeout=3.0)
        return True
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not (_db_ok() and _vroom_ok()), reason="needs database and vroom"
)

client = TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    created: list[int] = []

    def factory(specs, date_mode=DateMode.optimized):
        """specs: dicts with optional completed day/hour and lon offset."""
        tour = Tour(
            customer="Aldi Nord",
            calendar_week=27,
            date_from=MONDAY,
            date_to=FRIDAY,
            status=TourStatus.planned,
            date_mode=date_mode,
        )
        session.add(tour)
        session.flush()
        created.append(tour.id)
        stops = []
        for i, spec in enumerate(specs):
            lon = 12.3 + i * 0.01
            done_day = spec.get("done_day")
            stop = Stop(
                tour_id=tour.id,
                row_index=i,
                customer=f"Market {i}",
                status="confirmed",
                status_hint="pending",
                service_minutes=60,
                geom=WKTElement(f"POINT({lon} 51.3)", srid=4326),
                assigned_day=done_day or spec.get("assigned_day"),
                sequence=spec.get("sequence"),
                completed_at=(
                    datetime(
                        done_day.year,
                        done_day.month,
                        done_day.day,
                        spec.get("done_hour", 9),
                        0,
                        tzinfo=UTC,
                    )
                    if done_day
                    else None
                ),
            )
            session.add(stop)
            stops.append(stop)
        session.commit()
        return tour.id, [s.id for s in stops]

    yield session, factory

    for tid in created:
        session.query(Stop).filter(Stop.tour_id == tid).delete()
        session.query(Tour).filter(Tour.id == tid).delete()
    session.commit()
    session.close()


def _replan(session, tour_id, from_date):
    return optimise_tour(
        session,
        session.get(Tour, tour_id),
        config=CONFIG,
        matrix_provider=_zero_matrix,
        vroom_client=VroomClient(base_url=settings.vroom_url),
        from_date=from_date,
    )


def test_replan_keeps_completed_and_uses_remaining_days_only(db):
    session, factory = db
    # Two stops finished Mon/Tue; four open, one of them stranded on Monday.
    tour_id, ids = factory(
        [
            {"done_day": MONDAY, "sequence": 1},
            {"done_day": MONDAY + timedelta(days=1), "sequence": 1},
            {"assigned_day": MONDAY, "sequence": 2},  # missed on Monday
            {},
            {},
            {},
        ]
    )

    result = _replan(session, tour_id, from_date=WEDNESDAY)

    assert result.unassigned == []
    assert [d.date for d in result.days] == [
        WEDNESDAY,
        WEDNESDAY + timedelta(days=1),
        FRIDAY,
    ]

    for sid, spec_done in zip(
        ids[:2], (MONDAY, MONDAY + timedelta(days=1)), strict=True
    ):
        stop = session.get(Stop, sid)
        session.refresh(stop)
        assert stop.completed_at is not None
        assert stop.assigned_day == spec_done  # history untouched
        assert stop.sequence == 1

    for sid in ids[2:]:
        stop = session.get(Stop, sid)
        session.refresh(stop)
        assert stop.assigned_day is not None
        assert stop.assigned_day >= WEDNESDAY  # backlog moved forward


def test_replan_after_the_week_reports_no_days(db):
    session, factory = db
    tour_id, ids = factory([{"done_day": MONDAY, "sequence": 1}, {}, {}])

    result = _replan(session, tour_id, from_date=FRIDAY + timedelta(days=3))

    assert result.days == []
    assert {u.stop_id for u in result.unassigned} == set(ids[1:])
    assert all(u.reason == REASON_NO_DAYS for u in result.unassigned)
    done = session.get(Stop, ids[0])
    session.refresh(done)
    assert done.assigned_day == MONDAY


def test_last_completed_coord_is_latest_completion(db):
    session, factory = db
    tour_id, ids = factory(
        [
            {"done_day": MONDAY, "done_hour": 9, "sequence": 1},
            {"done_day": MONDAY, "done_hour": 15, "sequence": 2},  # latest
            {},
        ]
    )

    coord = _last_completed_coord(session, tour_id)
    assert coord is not None
    assert coord[0] == pytest.approx(12.31)  # stop index 1's longitude


def test_current_plan_mirrors_stored_schedule(db):
    session, factory = db
    tour_id, ids = factory([{}, {}, {}, {}])
    optimise_tour(
        session,
        session.get(Tour, tour_id),
        config=CONFIG,
        matrix_provider=_zero_matrix,
        vroom_client=VroomClient(base_url=settings.vroom_url),
    )

    plan = current_plan(session, session.get(Tour, tour_id), CONFIG)

    assert [d.date for d in plan.days] == [MONDAY + timedelta(days=i) for i in range(5)]
    planned = {s.stop_id: (d.date, s.sequence) for d in plan.days for s in d.stops}
    assert set(planned) == set(ids)
    for sid in ids:
        stop = session.get(Stop, sid)
        session.refresh(stop)
        assert planned[sid] == (stop.assigned_day, stop.sequence)


def test_move_stop_resequences_both_days_and_clears_eta(db):
    session, factory = db
    tour_id, ids = factory(
        [
            {"assigned_day": MONDAY, "sequence": 1},
            {"assigned_day": MONDAY, "sequence": 2},
            {"assigned_day": WEDNESDAY, "sequence": 1},
        ]
    )
    moved = session.get(Stop, ids[0])
    moved.eta = datetime(2026, 6, 29, 9, 0, tzinfo=UTC)
    session.commit()

    move_stop(session, moved, WEDNESDAY, position=1)

    by_id = {sid: session.get(Stop, sid) for sid in ids}
    for stop in by_id.values():
        session.refresh(stop)
    assert (by_id[ids[0]].assigned_day, by_id[ids[0]].sequence) == (WEDNESDAY, 1)
    assert by_id[ids[0]].eta is None
    assert (by_id[ids[2]].assigned_day, by_id[ids[2]].sequence) == (WEDNESDAY, 2)
    assert (by_id[ids[1]].assigned_day, by_id[ids[1]].sequence) == (MONDAY, 1)

    # Off the plan entirely: lands in current_plan's unassigned with a
    # human-readable manual reason.
    move_stop(session, by_id[ids[0]], None)
    session.refresh(by_id[ids[0]])
    assert by_id[ids[0]].assigned_day is None
    plan = current_plan(session, session.get(Tour, tour_id), CONFIG)
    assert {(u.stop_id, u.reason) for u in plan.unassigned} == {
        (ids[0], REASON_REMOVED_MANUALLY)
    }


def test_plan_endpoints_move_and_validate(db):
    session, factory = db
    tour_id, ids = factory(
        [
            {"assigned_day": MONDAY, "sequence": 1},
            {"assigned_day": MONDAY, "sequence": 2},
        ]
    )

    # Outside the tour's week -> rejected.
    bad = client.patch(f"/stops/{ids[0]}/plan", json={"assigned_day": "2026-08-01"})
    assert bad.status_code == 422

    ok = client.patch(f"/stops/{ids[0]}/plan", json={"assigned_day": str(WEDNESDAY)})
    assert ok.status_code == 200
    assert ok.json()["assigned_day"] == str(WEDNESDAY)
    assert ok.json()["sequence"] == 1

    plan = client.get(f"/tours/{tour_id}/plan").json()
    by_date = {d["date"]: [s["stop_id"] for s in d["stops"]] for d in plan["days"]}
    assert by_date[str(WEDNESDAY)] == [ids[0]]
    assert by_date[str(MONDAY)] == [ids[1]]
