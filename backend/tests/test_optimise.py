"""Integration tests for POST /tours/{id}/optimise (via optimise_tour).

Requires a reachable database (migrations applied) and a running Vroom. The
OSRM matrix is injected (all-zero travel), so Vroom runs in matrix mode and
neither OSRM nor the network is touched. Skipped when either service is down.
"""

from datetime import date, time

import httpx
import pytest
from geoalchemy2.elements import WKTElement

from app.config import settings
from app.db import SessionLocal, engine
from app.models.stop import Stop
from app.models.tour import Tour
from app.routing.vroom import VroomClient
from app.services.optimiser import OptimiseConfig, optimise_tour

MONDAY = date(2026, 6, 29)
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


def _make_tour(db, date_from, date_to, specs):
    """specs: list of (service_minutes, closing_time). Returns (tour_id, [ids])."""
    tour = Tour(
        customer="Aldi Nord",
        calendar_week=27,
        date_from=date_from,
        date_to=date_to,
        status="confirmed",
    )
    db.add(tour)
    db.flush()
    ids = []
    for i, (service_minutes, closing_time) in enumerate(specs):
        stop = Stop(
            tour_id=tour.id,
            row_index=i,
            customer=f"Market {i}",
            status="confirmed",
            status_hint="pending",
            service_minutes=service_minutes,
            closing_time=closing_time,
            geom=WKTElement(f"POINT({12.3 + i * 0.01} {51.3 + i * 0.01})", srid=4326),
        )
        db.add(stop)
        ids.append(stop)
    db.commit()
    result = (tour.id, [s.id for s in ids])
    return result


@pytest.fixture
def db():
    session = SessionLocal()
    created_tours: list[int] = []

    def factory(date_from, date_to, specs):
        tour_id, stop_ids = _make_tour(session, date_from, date_to, specs)
        created_tours.append(tour_id)
        return tour_id, stop_ids

    yield session, factory

    for tid in created_tours:
        session.query(Stop).filter(Stop.tour_id == tid).delete()
        session.query(Tour).filter(Tour.id == tid).delete()
    session.commit()
    session.close()


def _optimise(session, tour_id):
    tour = session.get(Tour, tour_id)
    return optimise_tour(
        session,
        tour,
        config=CONFIG,
        matrix_provider=_zero_matrix,
        vroom_client=VroomClient(base_url=settings.vroom_url),
    )


def test_all_stops_assigned_within_window(db):
    session, factory = db
    # 8 markets, 60 min each, across a Mon–Fri week -> all assignable.
    tour_id, stop_ids = factory(MONDAY, FRIDAY, [(60, None)] * 8)

    result = _optimise(session, tour_id)

    assert result.unassigned == []
    assigned = 0
    for day in result.days:
        for ds in day.stops:
            assert time(7, 0) <= ds.eta <= time(19, 0)
            assigned += 1
        if day.day_end is not None:
            assert day.day_end <= time(19, 0)
        # sequences are 1..n within the day
        assert [s.sequence for s in day.stops] == list(range(1, len(day.stops) + 1))
    assert assigned == 8

    for sid in stop_ids:
        stop = session.get(Stop, sid)
        session.refresh(stop)
        assert stop.assigned_day is not None
        assert stop.sequence is not None


def test_early_closing_store_scheduled_early(db):
    session, factory = db
    # Stop 0 closes at 12:00 with a 3h service -> must start by 09:00.
    tour_id, stop_ids = factory(
        MONDAY, FRIDAY, [(180, time(12, 0)), (60, None), (60, None)]
    )
    early_id = stop_ids[0]

    result = _optimise(session, tour_id)

    assert all(u.stop_id != early_id for u in result.unassigned)
    early = session.get(Stop, early_id)
    session.refresh(early)
    assert early.eta is not None
    assert early.eta.time() <= time(9, 0)


def test_overload_surfaces_unassigned(db):
    session, factory = db
    # One working day, 10 markets at 2h each = 20h >> 12h window.
    tour_id, stop_ids = factory(MONDAY, MONDAY, [(120, None)] * 10)

    result = _optimise(session, tour_id)

    assert len(result.unassigned) > 0
    assert all(u.reason == "exceeds available days" for u in result.unassigned)
    for u in result.unassigned:
        stop = session.get(Stop, u.stop_id)
        session.refresh(stop)
        assert stop.assigned_day is None
