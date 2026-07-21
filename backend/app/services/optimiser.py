"""Multi-day tour optimisation via Vroom.

Models the week as one vehicle per working day (no depot), and each confirmed
market as a job with one time window per day. Time is expressed as absolute
unix seconds throughout, matching the OSRM duration matrix (also seconds).

Key modelling choices:
- The first working day starts at the company base (settings.default_start_*,
  geocoded via the cached geocoder) with real travel cost, so day 1 is routed
  as the actual drive out from HQ. Later days have NO start/end (the crew
  overnights in hotels along the route), and every vehicle's time_window is
  bounded to its own day, so the solver's choice of vehicle == choice of day.
- A job carries one window per working day. Only the window on the vehicle's own
  day overlaps that vehicle's time_window, so picking a vehicle picks the day.
- tour.date_mode decides how binding the plan's Datum column is. 'fixed': a
  dated stop gets only its own day's window — the plan decides the day, the
  solver only sequences within it. 'optimized': dates are ignored and the
  solver assigns days itself, guarded by region clustering (below).
- Guardrail for 'optimized': stops are clustered by proximity, clusters whose
  centroids lie within max_day_span_km of each other are grouped, and each
  group receives its own share of the week's days (windows only on those
  days), blocks ordered by distance from the company base — the week reads as
  one journey out from HQ, so a region on the way out is served on day 1. A
  single day therefore never mixes far-apart regions, which zero-ish looking
  travel in the matrix would otherwise invite. Regions that can't get a day
  are returned as unassigned.
- Vroom time windows constrain when *service starts*. To force "done before the
  store closes", each day's window end is `close - service`, not `close`.
- The OSRM matrix is fetched explicitly and passed to Vroom (matrix mode); the
  solver does not call a router. `matrix_provider` is injectable for testing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models.service_record import ServiceRecord, learned_minutes, task_signature
from app.models.stop import Stop
from app.models.store import Store
from app.models.tour import DateMode, Tour
from app.routing.osrm import OSRMClient
from app.routing.vroom import VroomClient
from app.schemas.optimise import DayStop, DaySummary, OptimiseResult, UnassignedStop
from app.services.geocoding import geocode_address
from app.services.scheduling import effective_window

Coordinate = tuple[float, float]  # (lon, lat)
MatrixProvider = Callable[[Sequence[Coordinate]], list[list[int]]]

REASON_NO_WINDOW = "no feasible time window"
REASON_NO_DAYS = "exceeds available days"
REASON_MISSING_LOCATION = "missing location"
REASON_STORE_NOT_GEOCODED = "store not geocoded"
REASON_FAR_REGION = "too far from the rest of the tour to fit into the week"
REASON_NOT_SCHEDULED = "not scheduled yet"
REASON_REMOVED_MANUALLY = "taken off the plan by hand"


@dataclass
class OptimiseConfig:
    working_start: time
    working_end: time
    default_service_minutes: int
    skip_weekdays: set[int]
    near_limit_seconds: int
    respect_stop_dates: bool = True
    max_day_span_km: float = 120.0

    @classmethod
    def from_settings(cls) -> OptimiseConfig:
        return cls(
            working_start=settings.working_day_start,
            working_end=settings.working_day_end,
            default_service_minutes=settings.default_service_minutes,
            skip_weekdays=settings.skip_weekday_set,
            near_limit_seconds=settings.near_limit_minutes * 60,
            respect_stop_dates=settings.respect_stop_dates,
            max_day_span_km=settings.max_day_span_km,
        )


def _epoch(day: date, clock: time) -> int:
    """Absolute unix seconds for a clock time on a date (UTC convention).

    A fixed UTC convention keeps windows and the matrix in one consistent time
    base; the absolute offset is irrelevant since everything is relative.
    """
    return int(
        datetime(
            day.year,
            day.month,
            day.day,
            clock.hour,
            clock.minute,
            clock.second,
            tzinfo=UTC,
        ).timestamp()
    )


def _from_epoch(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=UTC)


def _date_range(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def working_days(tour: Tour, config: OptimiseConfig) -> list[date]:
    return [
        d
        for d in _date_range(tour.date_from, tour.date_to)
        if d.weekday() not in config.skip_weekdays
    ]


def _osrm_matrix(coords: Sequence[Coordinate]) -> list[list[int]]:
    durations = OSRMClient().duration_matrix(coords)
    return [[int(round(value)) for value in row] for row in durations]


def optimise_tour(
    db: Session,
    tour: Tour,
    *,
    config: OptimiseConfig | None = None,
    matrix_provider: MatrixProvider | None = None,
    vroom_client: VroomClient | None = None,
    from_date: date | None = None,
) -> OptimiseResult:
    """Plan the tour's days. With ``from_date``, re-plan mid-week: only the
    days from that date on are (re)used, completed stops keep their history,
    and everything still open — including stops stranded on earlier days —
    is redistributed over the remaining days."""
    config = config or OptimiseConfig.from_settings()
    matrix_provider = matrix_provider or _osrm_matrix
    vroom_client = vroom_client or VroomClient()

    week_days = working_days(tour, config)
    days = [d for d in week_days if from_date is None or d >= from_date]

    # Completed stops are history — never re-planned, in any mode; they keep
    # their day/sequence for the record (and the P4 service-time learner).
    stops = list(
        db.scalars(
            select(Stop).where(
                Stop.tour_id == tour.id,
                Stop.status == "confirmed",
                Stop.status_hint != "skip",
                Stop.completed_at.is_(None),
            )
            # effective hours/geom read through to the store; load it in one go.
            .options(selectinload(Stop.store), selectinload(Stop.tasks))
        )
    )

    # Fresh run: clear any previous assignment so unassigned stops end up null.
    for stop in stops:
        stop.assigned_day = None
        stop.sequence = None
        stop.eta = None
        stop.unassigned_reason = None

    coords_by_id = _coords_by_id(db, [s.id for s in stops])

    # A stop's own estimate is authoritative (it may be crew-edited); a stop
    # without one falls back to its catalog store's learned minutes for the
    # stop's own task profile, then the store-wide learned-then-default
    # minutes (P4), then the global default.
    store_minutes = _store_service_minutes(db, stops)
    profile_minutes = _profile_service_minutes(db, stops)
    stop_signature = {s.id: task_signature(t.task_type for t in s.tasks) for s in stops}

    def service_minutes_for(stop: Stop) -> int:
        return (
            stop.service_minutes
            or profile_minutes.get((stop.store_id, stop_signature[stop.id]))
            or store_minutes.get(stop.store_id)
            or config.default_service_minutes
        )

    # Where the first planned day starts. A fresh week departs from the
    # company base; a mid-week re-plan departs from wherever the crew last
    # was — the most recently completed stop. With neither (a re-plan before
    # anything was done), the first day free-starts like the hotel days. A
    # failed base geocode degrades to a free start rather than blocking.
    depot_coord = _last_completed_coord(db, tour.id)
    if depot_coord is None and days and week_days and days[0] == week_days[0]:
        depot_coord = geocode_address(
            db,
            settings.default_start_street,
            settings.default_start_postal_code,
            settings.default_start_city,
        )

    # 'fixed' pins dated stops to their plan day; 'optimized' lets the solver
    # choose days, constrained to region day-groups so one day never mixes
    # far-apart areas. The base coordinate orders the groups: only day 1
    # starts at the base, so the region nearest it must get the week's first
    # days, not whatever block is left over.
    pin_dates = config.respect_stop_dates and tour.date_mode == DateMode.fixed
    days_by_stop: dict[int, list[date]] = {}
    if not pin_dates and days:
        days_by_stop = plan_region_days(
            {
                s.id: (coords_by_id[s.id], service_minutes_for(s) * 60)
                for s in stops
                if s.id in coords_by_id
            },
            days,
            config.max_day_span_km,
            depot=depot_coord,
        )

    schedulable: list[_Job] = []
    unassigned: list[UnassignedStop] = []

    def mark_unassigned(stop: Stop, reason: str) -> None:
        stop.unassigned_reason = reason
        unassigned.append(UnassignedStop(stop_id=stop.id, reason=reason))

    for stop in stops:
        if stop.id not in coords_by_id:
            # A linked store without geometry is a data problem worth naming;
            # an unlinked stop simply has no location yet. Neither ever falls
            # back to the claim's geocode — a bad printed row must not be able
            # to misroute anyone.
            mark_unassigned(
                stop,
                (
                    REASON_STORE_NOT_GEOCODED
                    if stop.store_id is not None
                    else REASON_MISSING_LOCATION
                ),
            )
            continue

        stop_days = days_by_stop.get(stop.id, days) if not pin_dates else days
        if not stop_days:
            mark_unassigned(stop, REASON_NO_DAYS if not days else REASON_FAR_REGION)
            continue

        service = service_minutes_for(stop) * 60
        windows = _job_windows(stop, stop_days, service, config, pin_dates)
        if not windows:
            mark_unassigned(stop, REASON_NO_DAYS if not days else REASON_NO_WINDOW)
            continue

        schedulable.append(
            _Job(
                stop=stop,
                coord=coords_by_id[stop.id],
                service=service,
                windows=windows,
            )
        )

    if not schedulable or not days:
        db.commit()
        return OptimiseResult(
            tour_id=tour.id,
            date_mode=tour.date_mode,
            days=[
                DaySummary(
                    date=d,
                    stops=[],
                    drive_seconds=0,
                    service_seconds=0,
                    day_end=None,
                    near_limit=False,
                )
                for d in days
            ],
            unassigned=unassigned,
        )

    # Solver-chosen days spread the work over every day rather than cramming
    # the fewest: within each region's block of days, a day takes at most the
    # even share, so Friday becomes a lighter day instead of an empty one.
    # Pinned (fixed-mode) plans keep whatever the paper says — a cap could
    # unassign dated stops.
    max_tasks_by_day: dict[date, int] | None = None
    if not pin_dates and days_by_stop:
        block_sizes: dict[tuple[date, ...], int] = {}
        for job in schedulable:
            block = tuple(days_by_stop.get(job.stop.id, days))
            block_sizes[block] = block_sizes.get(block, 0) + 1
        max_tasks_by_day = {}
        for block, size in block_sizes.items():
            for day in block:
                max_tasks_by_day[day] = -(-size // len(block))

    problem = _build_problem(
        schedulable,
        days,
        config,
        matrix_provider,
        depot_coord=depot_coord,
        max_tasks_by_day=max_tasks_by_day,
    )
    solution = vroom_client.solve(problem)

    stop_by_id = {job.stop.id: job.stop for job in schedulable}
    summaries = _apply_solution(solution, days, stop_by_id, config)

    for entry in solution.get("unassigned", []):
        mark_unassigned(stop_by_id[int(entry["id"])], REASON_NO_DAYS)

    db.commit()
    return OptimiseResult(
        tour_id=tour.id,
        date_mode=tour.date_mode,
        days=summaries,
        unassigned=unassigned,
    )


@dataclass
class _Job:
    stop: Stop
    coord: Coordinate
    service: int
    windows: list[list[int]]


def _store_service_minutes(db: Session, stops: Sequence[Stop]) -> dict[int, int]:
    """Catalog fallback minutes per store id: learned (P4) over hand-set default."""
    store_ids = {s.store_id for s in stops if s.store_id is not None}
    if not store_ids:
        return {}
    rows = db.execute(
        select(
            Store.id,
            func.coalesce(Store.learned_service_minutes, Store.default_service_minutes),
        ).where(Store.id.in_(store_ids))
    ).all()
    return {store_id: minutes for store_id, minutes in rows if minutes is not None}


def _profile_service_minutes(
    db: Session, stops: Sequence[Stop]
) -> dict[tuple[int, str], int]:
    """Learned minutes per (store id, task signature), aggregated from the
    service ledger: the same store can take a different time depending on
    which service the visit is for (P4)."""
    store_ids = {s.store_id for s in stops if s.store_id is not None}
    if not store_ids:
        return {}
    rows = db.execute(
        select(
            ServiceRecord.store_id,
            ServiceRecord.task_signature,
            ServiceRecord.duration_minutes,
        ).where(ServiceRecord.store_id.in_(store_ids))
    ).all()
    durations: dict[tuple[int, str], list[int]] = {}
    for store_id, signature, minutes in rows:
        durations.setdefault((store_id, signature), []).append(minutes)
    return {
        key: estimate
        for key, values in durations.items()
        if (estimate := learned_minutes(values)) is not None
    }


def service_minutes_map(
    db: Session, stops: Sequence[Stop], config: OptimiseConfig | None = None
) -> dict[int, int]:
    """Best service-time estimate per stop id, using the same priority the
    solver applies: the stop's own override, then the learned per-task profile,
    then the store-wide learned/default, then the global default."""
    config = config or OptimiseConfig.from_settings()
    store_minutes = _store_service_minutes(db, stops)
    profile_minutes = _profile_service_minutes(db, stops)
    result: dict[int, int] = {}
    for s in stops:
        signature = task_signature(t.task_type for t in s.tasks)
        result[s.id] = (
            s.service_minutes
            or profile_minutes.get((s.store_id, signature))
            or store_minutes.get(s.store_id)
            or config.default_service_minutes
        )
    return result


def _last_completed_coord(db: Session, tour_id: int) -> Coordinate | None:
    """Where the crew last finished a stop — the mid-week re-plan start.

    Coordinates come from the store's geometry only — the plan's claimed
    geocode is diagnostic and never routes anyone.
    """
    row = db.execute(
        select(func.ST_X(Store.geom), func.ST_Y(Store.geom))
        .select_from(Stop)
        .join(Store, Stop.store_id == Store.id)
        .where(
            Stop.tour_id == tour_id,
            Stop.completed_at.isnot(None),
            Store.geom.isnot(None),
        )
        .order_by(Stop.completed_at.desc())
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None


def _coords_by_id(db: Session, stop_ids: list[int]) -> dict[int, Coordinate]:
    """Routable coordinate per stop id: the linked store's geometry, and
    nothing else. Stops absent from the result have no routable location."""
    if not stop_ids:
        return {}
    rows = db.execute(
        select(Stop.id, func.ST_X(Store.geom), func.ST_Y(Store.geom))
        .select_from(Stop)
        .join(Store, Stop.store_id == Store.id)
        .where(Stop.id.in_(stop_ids), Store.geom.isnot(None))
    ).all()
    return {sid: (lon, lat) for sid, lon, lat in rows}


# --- Stored plan: read + manual edits (no solver) -----------------------------


def _tour_plan_stops(db: Session, tour_id: int) -> list[Stop]:
    return list(
        db.scalars(
            select(Stop).where(
                Stop.tour_id == tour_id,
                Stop.status == "confirmed",
                Stop.status_hint != "skip",
            )
            # effective_geom reads through to the store; load it in one go.
            .options(selectinload(Stop.store))
        )
    )


def current_plan(
    db: Session, tour: Tour, config: OptimiseConfig | None = None
) -> OptimiseResult:
    """The schedule exactly as stored — what clients should read.

    Re-solving on read would silently overwrite completions-in-progress and
    manual edits, so the map loads this instead of POSTing optimise. Days are
    the tour's working days plus any day a stop was hand-moved to. Drive time
    and day-end are solver outputs and read as zero/empty here.
    """
    config = config or OptimiseConfig.from_settings()
    stops = _tour_plan_stops(db, tour.id)

    dates = sorted(
        set(working_days(tour, config))
        | {s.assigned_day for s in stops if s.assigned_day is not None}
    )

    summaries = []
    for day in dates:
        day_stops = sorted(
            (s for s in stops if s.assigned_day == day),
            key=lambda s: (s.sequence is None, s.sequence, s.id),
        )
        summaries.append(
            DaySummary(
                date=day,
                stops=[
                    DayStop(
                        stop_id=s.id,
                        sequence=s.sequence if s.sequence is not None else index + 1,
                        eta=s.eta.time() if s.eta is not None else None,
                    )
                    for index, s in enumerate(day_stops)
                ],
                drive_seconds=0,
                service_seconds=sum(
                    (s.service_minutes or config.default_service_minutes) * 60
                    for s in day_stops
                ),
                day_end=None,
                near_limit=False,
            )
        )

    unassigned = [
        UnassignedStop(
            stop_id=s.id,
            reason=s.unassigned_reason
            or (
                REASON_NOT_SCHEDULED
                if s.effective_geom is not None
                else (
                    REASON_STORE_NOT_GEOCODED
                    if s.store_id is not None
                    else REASON_MISSING_LOCATION
                )
            ),
        )
        for s in stops
        if s.assigned_day is None and s.completed_at is None
    ]
    return OptimiseResult(
        tour_id=tour.id, date_mode=tour.date_mode, days=summaries, unassigned=unassigned
    )


def move_stop(
    db: Session, stop: Stop, day: date | None, position: int | None = None
) -> None:
    """Manually move a stop to a day (1-based position, appended by default)
    or take it off the plan (day=None). Both affected days are re-sequenced;
    the moved stop's ETA is cleared — only the solver can estimate one.
    """

    def stops_of(day: date) -> list[Stop]:
        return list(
            db.scalars(
                select(Stop)
                .where(
                    Stop.tour_id == stop.tour_id,
                    Stop.assigned_day == day,
                    Stop.id != stop.id,
                )
                .order_by(Stop.sequence)
            )
        )

    source_day = stop.assigned_day
    stop.eta = None

    if day is None:
        stop.assigned_day = None
        stop.sequence = None
        stop.unassigned_reason = REASON_REMOVED_MANUALLY
    else:
        target = stops_of(day)
        index = len(target) if position is None else min(position - 1, len(target))
        target.insert(index, stop)
        stop.assigned_day = day
        stop.unassigned_reason = None
        for sequence, member in enumerate(target, start=1):
            member.sequence = sequence

    if source_day is not None and source_day != day:
        for sequence, member in enumerate(stops_of(source_day), start=1):
            member.sequence = sequence

    db.commit()


# --- Region guardrail (date_mode='optimized') --------------------------------

_EARTH_RADIUS_KM = 6371.0


def _haversine_km(a: Coordinate, b: Coordinate) -> float:
    lon1, lat1 = radians(a[0]), radians(a[1])
    lon2, lat2 = radians(b[0]), radians(b[1])
    h = (
        sin((lat2 - lat1) / 2) ** 2
        + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(h))


def _centroid(coords: list[Coordinate]) -> Coordinate:
    return (
        sum(c[0] for c in coords) / len(coords),
        sum(c[1] for c in coords) / len(coords),
    )


def _cluster_by_proximity(coords: list[Coordinate], eps_km: float) -> list[list[int]]:
    """Single-linkage clusters: index groups chained by hops of ≤ eps_km."""
    parent = list(range(len(coords)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(coords)):
        for j in range(i + 1, len(coords)):
            if _haversine_km(coords[i], coords[j]) <= eps_km:
                parent[find(i)] = find(j)

    clusters: dict[int, list[int]] = {}
    for i in range(len(coords)):
        clusters.setdefault(find(i), []).append(i)
    return list(clusters.values())


def _allocate_days(workloads: list[int], day_count: int) -> list[int]:
    """Days per group, for groups in workload-descending order.

    Proportional to workload, at least 1 per group while days remain (keeping
    a day back for each group still waiting); a group whose turn comes after
    the days ran out gets 0 — its stops must be reported unassigned.
    """
    counts: list[int] = []
    remaining_days = day_count
    remaining_work = sum(workloads)
    for index, work in enumerate(workloads):
        groups_after = len(workloads) - index - 1
        if remaining_days <= 0:
            counts.append(0)
            continue
        share = round(remaining_days * work / remaining_work) if remaining_work else 1
        reserve = min(groups_after, remaining_days - 1)
        count = max(1, min(share, remaining_days - reserve))
        counts.append(count)
        remaining_days -= count
        remaining_work -= work

    # Rounding can leave spare days; hand them to groups that got days,
    # biggest first (a zero-day group stays zero — no block position for it).
    index = 0
    while remaining_days > 0 and any(counts):
        if counts[index % len(counts)] > 0:
            counts[index % len(counts)] += 1
            remaining_days -= 1
        index += 1
    return counts


def plan_region_days(
    stops: dict[int, tuple[Coordinate, int]],
    days: list[date],
    max_span_km: float,
    depot: Coordinate | None = None,
) -> dict[int, list[date]]:
    """Split the week's days between geographic regions.

    ``stops`` maps stop id -> ((lon, lat), service seconds). Stops are
    clustered by proximity (single-linkage, eps = max_span_km / 4); clusters
    whose centroids all lie within max_span_km of each other merge into a
    day-group; each group gets a contiguous block of days sized by its share
    of the service workload. With ``depot`` given, blocks run in order of a
    group's distance from it: the week is one journey out from the base, so a
    region on the way out is served on day 1 (the only day that starts at the
    base) rather than on a leftover day at the week's end. The returned
    mapping gives every stop its allowed days — an empty list means the
    stop's region lost the allocation (more far-apart regions than days) and
    must be reported unassigned.
    """
    if not stops:
        return {}

    ids = list(stops)
    coords = [stops[sid][0] for sid in ids]
    clusters = _cluster_by_proximity(coords, max_span_km / 4)

    def cluster_workload(cluster: list[int]) -> int:
        return sum(stops[ids[i]][1] for i in cluster)

    clusters.sort(key=cluster_workload, reverse=True)

    # Greedy grouping: a cluster joins the first group it stays compatible
    # with (its centroid within max_span_km of every member cluster's).
    groups: list[dict] = []
    for cluster in clusters:
        centroid = _centroid([coords[i] for i in cluster])
        workload = cluster_workload(cluster)
        for group in groups:
            if all(
                _haversine_km(centroid, other) <= max_span_km
                for other in group["centroids"]
            ):
                group["indices"].extend(cluster)
                group["centroids"].append(centroid)
                group["workload"] += workload
                break
        else:
            groups.append(
                {
                    "indices": list(cluster),
                    "centroids": [centroid],
                    "workload": workload,
                }
            )

    day_counts = _allocate_days([g["workload"] for g in groups], len(days))

    # Sizing above is by workload; block *order* follows the drive out from
    # the base. Without a depot the workload order stands.
    order = list(range(len(groups)))
    if depot is not None:
        order.sort(
            key=lambda g: min(_haversine_km(depot, c) for c in groups[g]["centroids"])
        )

    allowed: dict[int, list[date]] = {}
    cursor = 0
    for g in order:
        block = days[cursor : cursor + day_counts[g]]
        cursor += day_counts[g]
        for i in groups[g]["indices"]:
            allowed[ids[i]] = block
    return allowed


def _job_windows(
    stop: Stop,
    days: list[date],
    service: int,
    config: OptimiseConfig,
    pin_dates: bool,
) -> list[list[int]]:
    # In fixed mode a stop dated by the plan is pinned to its day; the solver
    # only orders it within that day. A stop whose date isn't a working day
    # floats freely rather than becoming unschedulable.
    if pin_dates and stop.date is not None and stop.date in days:
        days = [stop.date]

    windows: list[list[int]] = []
    for day in days:
        eff_open, eff_close = effective_window(
            stop, config.working_start, config.working_end
        )
        start = _epoch(day, eff_open)
        # End is close - service so the whole service finishes before closing.
        end = _epoch(day, eff_close) - service
        if end >= start:
            windows.append([start, end])
    return windows


def _build_problem(
    jobs: list[_Job],
    days: list[date],
    config: OptimiseConfig,
    matrix_provider: MatrixProvider,
    *,
    depot_coord: Coordinate | None = None,
    max_tasks_by_day: dict[date, int] | None = None,
) -> dict:
    # The real depot (company base) travels at actual cost, so it joins the
    # OSRM matrix; the first day starts there.
    coords = [job.coord for job in jobs]
    if depot_coord is not None:
        coords = coords + [depot_coord]
    matrix = matrix_provider(coords)
    base_index = len(matrix) - 1 if depot_coord is not None else None

    # Vroom requires every vehicle to have a start or end, so a truly depot-less
    # vehicle is rejected. We append a virtual depot with zero travel to/from
    # every point and use it as an open-ended start: leaving it costs nothing,
    # so it has no effect on the plan or on reported drive time.
    free_index = len(matrix)
    matrix = [list(row) + [0] for row in matrix]
    matrix.append([0] * (free_index + 1))

    vehicles = [
        {
            "id": index,
            "profile": "car",
            # Day 1 departs from the company base; later days start wherever
            # the crew's hotel is, modelled as a free start.
            "start_index": (
                base_index if index == 0 and base_index is not None else free_index
            ),
            # Later days carry a growing fixed cost (30 min-equivalents), so
            # work fills the earliest days first and holes never open
            # mid-week; the max_tasks cap (solver-chosen days only) forces
            # the spill-over that keeps every day of the week in use.
            "costs": {"fixed": index * 1800},
            **(
                {"max_tasks": max_tasks_by_day[day]}
                if max_tasks_by_day is not None and day in max_tasks_by_day
                else {}
            ),
            "time_window": [
                _epoch(day, config.working_start),
                _epoch(day, config.working_end),
            ],
        }
        for index, day in enumerate(days)
    ]
    vroom_jobs = [
        {
            "id": job.stop.id,
            "location_index": index,
            "service": job.service,
            "time_windows": job.windows,
        }
        for index, job in enumerate(jobs)
    ]
    return {
        "vehicles": vehicles,
        "jobs": vroom_jobs,
        "matrices": {"car": {"durations": matrix}},
    }


def _apply_solution(
    solution: dict,
    days: list[date],
    stop_by_id: dict[int, Stop],
    config: OptimiseConfig,
) -> list[DaySummary]:
    routes_by_vehicle = {
        route["vehicle"]: route for route in solution.get("routes", [])
    }
    summaries: list[DaySummary] = []

    for vehicle_id, day in enumerate(days):
        route = routes_by_vehicle.get(vehicle_id)
        if route is None:
            summaries.append(
                DaySummary(
                    date=day,
                    stops=[],
                    drive_seconds=0,
                    service_seconds=0,
                    day_end=None,
                    near_limit=False,
                )
            )
            continue

        day_stops: list[DayStop] = []
        last_end: int | None = None
        sequence = 0
        for step in route["steps"]:
            if step.get("type") != "job":
                continue
            sequence += 1
            stop = stop_by_id[step["job"]]
            arrival = step["arrival"]
            stop.assigned_day = day
            stop.sequence = sequence
            stop.eta = _from_epoch(arrival)
            last_end = arrival + step.get("service", 0)
            day_stops.append(
                DayStop(
                    stop_id=stop.id,
                    sequence=sequence,
                    eta=_from_epoch(arrival).time(),
                )
            )

        window_end = _epoch(day, config.working_end)
        near_limit = last_end is not None and (
            window_end - last_end <= config.near_limit_seconds
        )
        summaries.append(
            DaySummary(
                date=day,
                stops=day_stops,
                drive_seconds=int(route.get("duration", 0)),
                service_seconds=int(route.get("service", 0)),
                day_end=_from_epoch(last_end).time() if last_end is not None else None,
                near_limit=bool(near_limit),
            )
        )

    return summaries
