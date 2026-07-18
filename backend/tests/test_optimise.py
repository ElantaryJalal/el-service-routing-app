"""Integration tests for POST /tours/{id}/optimise (via optimise_tour).

Requires a reachable database (migrations applied) and a running Vroom. The
OSRM matrix is injected (all-zero travel), so Vroom runs in matrix mode and
neither OSRM nor the network is touched. Skipped when either service is down.
"""

from datetime import date, time, timedelta

import httpx
import pytest
from geoalchemy2.elements import WKTElement

from app.config import settings
from app.db import SessionLocal, engine
from app.models.stop import Stop
from app.models.store import Store
from app.models.tour import DateMode, Tour, TourStatus
from app.routing.vroom import VroomClient
from app.services.optimiser import (
    REASON_FAR_REGION,
    REASON_STORE_NOT_GEOCODED,
    OptimiseConfig,
    optimise_tour,
)

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


def _make_tour(db, date_from, date_to, specs, date_mode=DateMode.fixed):
    """specs: list of (service_minutes, closing_time) tuples, or dicts adding
    optional lon/lat/date per stop. Returns (tour_id, [stop ids], [store ids]).

    Geometry and closing hours live on the store (0012): each spec gets its
    own store carrying them; the stop only links it.
    """
    tour = Tour(
        customer="Aldi Nord",
        calendar_week=27,
        date_from=date_from,
        date_to=date_to,
        status=TourStatus.planned,
        date_mode=date_mode,
    )
    db.add(tour)
    db.flush()
    stops = []
    store_ids = []
    for i, spec in enumerate(specs):
        if isinstance(spec, tuple):
            spec = {"service_minutes": spec[0], "closing_time": spec[1]}
        lon = spec.get("lon", 12.3 + i * 0.01)
        lat = spec.get("lat", 51.3 + i * 0.01)
        store = Store(
            name=f"Optimise-Test Market {i}",
            closing_time=spec.get("closing_time"),
            geom=(
                None
                if spec.get("store_geom") is None and "store_geom" in spec
                else WKTElement(f"POINT({lon} {lat})", srid=4326)
            ),
        )
        db.add(store)
        db.flush()
        store_ids.append(store.id)
        stop = Stop(
            tour_id=tour.id,
            row_index=i,
            customer=f"Market {i}",
            store_id=store.id,
            status="confirmed",
            status_hint="pending",
            date=spec.get("date"),
            service_minutes=spec.get("service_minutes"),
            claimed_geom=spec.get("claimed_geom"),
        )
        db.add(stop)
        stops.append(stop)
    db.commit()
    return (tour.id, [s.id for s in stops], store_ids)


@pytest.fixture
def db():
    session = SessionLocal()
    created_tours: list[int] = []
    created_stores: list[int] = []

    def factory(date_from, date_to, specs, **kwargs):
        tour_id, stop_ids, store_ids = _make_tour(
            session, date_from, date_to, specs, **kwargs
        )
        created_tours.append(tour_id)
        created_stores.extend(store_ids)
        return tour_id, stop_ids

    yield session, factory

    for tid in created_tours:
        session.query(Stop).filter(Stop.tour_id == tid).delete()
        session.query(Tour).filter(Tour.id == tid).delete()
    if created_stores:
        session.query(Store).filter(Store.id.in_(created_stores)).delete()
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


# --- date_mode ---------------------------------------------------------------

# Two areas far beyond the 120 km default guardrail (~440 km apart).
LEIPZIG = (12.37, 51.34)
AACHEN = (6.08, 50.77)


def _dated_spec(day, lon_offset=0.0, base=LEIPZIG):
    return {
        "service_minutes": 60,
        "closing_time": None,
        "date": day,
        "lon": base[0] + lon_offset,
        "lat": base[1],
    }


def test_fixed_mode_reproduces_plan_dates(db):
    session, factory = db
    # Two markets per day, Mon-Wed, each pinned by the plan's Datum column.
    plan_days = [MONDAY, MONDAY + timedelta(days=1), MONDAY + timedelta(days=2)]
    specs = [
        _dated_spec(day, lon_offset=i * 0.01)
        for i, day in enumerate(d for d in plan_days for _ in range(2))
    ]
    tour_id, stop_ids = factory(MONDAY, FRIDAY, specs, date_mode=DateMode.fixed)

    result = _optimise(session, tour_id)

    assert result.date_mode == DateMode.fixed
    assert result.unassigned == []
    for sid, spec in zip(stop_ids, specs, strict=True):
        stop = session.get(Stop, sid)
        session.refresh(stop)
        assert stop.assigned_day == spec["date"]


def test_optimized_mode_moves_stops_off_their_plan_date(db):
    session, factory = db
    # 20 markets all dated Monday: pinned, only 12×60min fit the 12h day.
    specs = [_dated_spec(MONDAY, lon_offset=i * 0.005) for i in range(20)]
    tour_id, _ = factory(MONDAY, FRIDAY, specs, date_mode=DateMode.fixed)
    overloaded = _optimise(session, tour_id)
    assert len(overloaded.unassigned) > 0

    # The same plan in optimized mode spreads across the week instead.
    tour_id, _ = factory(MONDAY, FRIDAY, specs, date_mode=DateMode.optimized)
    result = _optimise(session, tour_id)

    assert result.date_mode == DateMode.optimized
    assert result.unassigned == []
    used_days = [d.date for d in result.days if d.stops]
    assert len(used_days) >= 2
    assert any(d != MONDAY for d in used_days)


def test_optimized_mode_spreads_over_all_days(db):
    session, factory = db
    # 20 undated markets in one region, 5-day week: solver-chosen days must
    # use the whole week (4 per day), not cram the fewest days and leave
    # Friday empty.
    specs = [
        {
            "service_minutes": 60,
            "closing_time": None,
            "lon": LEIPZIG[0] + i * 0.005,
            "lat": LEIPZIG[1],
        }
        for i in range(20)
    ]
    tour_id, _ = factory(MONDAY, FRIDAY, specs, date_mode=DateMode.optimized)

    result = _optimise(session, tour_id)

    assert result.unassigned == []
    assert [len(d.stops) for d in result.days] == [4, 4, 4, 4, 4]


def test_optimized_mode_never_mixes_far_regions(db):
    session, factory = db
    # Six markets around Leipzig, six around Aachen, zero travel cost in the
    # injected matrix — exactly the trap the guardrail must catch.
    specs = [
        {
            "service_minutes": 60,
            "closing_time": None,
            "lon": base[0] + i * 0.01,
            "lat": base[1],
        }
        for base in (LEIPZIG, AACHEN)
        for i in range(6)
    ]
    tour_id, stop_ids = factory(MONDAY, FRIDAY, specs, date_mode=DateMode.optimized)
    leipzig_ids = set(stop_ids[:6])
    aachen_ids = set(stop_ids[6:])

    result = _optimise(session, tour_id)

    assert result.unassigned == []
    for day in result.days:
        ids = {s.stop_id for s in day.stops}
        assert not (
            ids & leipzig_ids and ids & aachen_ids
        ), f"day {day.date} mixes regions {ids}"


# --- store geometry is the only routable truth -------------------------------


def test_typoed_claim_routes_to_store_location(db):
    """A stop whose claimed address is wrong (typo'd PLZ geocoding ~40 km away)
    must route to the STORE's verified location — the whole point of the
    refactor: a bad printed row can no longer misroute anyone."""
    session, factory = db
    store_coord = (12.3731, 51.3397)  # Leipzig — where the store really is
    wrong_coord = (12.30, 51.70)  # ~40 km north — where the typo geocoded to
    specs = [
        {
            "service_minutes": 60,
            "closing_time": None,
            "lon": store_coord[0],
            "lat": store_coord[1],
            "claimed_geom": WKTElement(
                f"POINT({wrong_coord[0]} {wrong_coord[1]})", srid=4326
            ),
        },
        {"service_minutes": 60, "closing_time": None},
    ]
    tour_id, stop_ids = factory(MONDAY, FRIDAY, specs)

    seen_coords: list[list] = []

    def capturing_matrix(coords):
        seen_coords.append(list(coords))
        return _zero_matrix(coords)

    tour = session.get(Tour, tour_id)
    result = optimise_tour(
        session,
        tour,
        config=CONFIG,
        matrix_provider=capturing_matrix,
        vroom_client=VroomClient(base_url=settings.vroom_url),
    )

    assert result.unassigned == []
    routed = {(round(lon, 4), round(lat, 4)) for lon, lat in seen_coords[0]}
    assert (round(store_coord[0], 4), round(store_coord[1], 4)) in routed
    assert (round(wrong_coord[0], 4), round(wrong_coord[1], 4)) not in routed


def test_store_without_geom_is_unassigned_not_claimed(db):
    """No silent fallback to the claim: a linked store lacking geometry takes
    the stop off the plan with an explicit reason."""
    session, factory = db
    specs = [
        {"service_minutes": 60, "closing_time": None},
        {
            "service_minutes": 60,
            "closing_time": None,
            "store_geom": None,  # store exists but was never geocoded
            "claimed_geom": WKTElement("POINT(12.40 51.40)", srid=4326),
        },
    ]
    tour_id, stop_ids = factory(MONDAY, FRIDAY, specs)

    result = _optimise(session, tour_id)

    assert [u.stop_id for u in result.unassigned] == [stop_ids[1]]
    assert result.unassigned[0].reason == REASON_STORE_NOT_GEOCODED


def test_optimized_mode_far_region_overflows_to_unassigned(db):
    session, factory = db
    # One working day but two far-apart regions: the smaller region can't get
    # a day and must surface as unassigned rather than force an insane route.
    specs = [
        {
            "service_minutes": 60,
            "closing_time": None,
            "lon": LEIPZIG[0] + i * 0.01,
            "lat": LEIPZIG[1],
        }
        for i in range(2)
    ] + [
        {
            "service_minutes": 60,
            "closing_time": None,
            "lon": AACHEN[0],
            "lat": AACHEN[1],
        }
    ]
    tour_id, stop_ids = factory(MONDAY, MONDAY, specs, date_mode=DateMode.optimized)

    result = _optimise(session, tour_id)

    assert [u.stop_id for u in result.unassigned] == [stop_ids[2]]
    assert result.unassigned[0].reason == REASON_FAR_REGION
    assigned = {s.stop_id for d in result.days for s in d.stops}
    assert assigned == set(stop_ids[:2])
