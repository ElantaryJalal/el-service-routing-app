"""Multi-day tour optimisation via Vroom.

Models the week as one vehicle per working day (no depot), and each confirmed
market as a job with one time window per day. Time is expressed as absolute
unix seconds throughout, matching the OSRM duration matrix (also seconds).

Key modelling choices:
- Vehicles have NO start/end (markets-only) and a time_window bounded to their
  own day, so the solver's choice of vehicle == choice of day.
- A job carries one window per working day. Only the window on the vehicle's own
  day overlaps that vehicle's time_window, so picking a vehicle picks the day.
- Vroom time windows constrain when *service starts*. To force "done before the
  store closes", each day's window end is `close - service`, not `close`.
- The OSRM matrix is fetched explicitly and passed to Vroom (matrix mode); the
  solver does not call a router. `matrix_provider` is injectable for testing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.stop import Stop
from app.models.tour import Tour
from app.routing.osrm import OSRMClient
from app.routing.vroom import VroomClient
from app.schemas.optimise import DayStop, DaySummary, OptimiseResult, UnassignedStop
from app.services.scheduling import effective_window

Coordinate = tuple[float, float]  # (lon, lat)
MatrixProvider = Callable[[Sequence[Coordinate]], list[list[int]]]

REASON_NO_WINDOW = "no feasible time window"
REASON_NO_DAYS = "exceeds available days"
REASON_MISSING_LOCATION = "missing location"


@dataclass
class OptimiseConfig:
    working_start: time
    working_end: time
    default_service_minutes: int
    skip_weekdays: set[int]
    near_limit_seconds: int

    @classmethod
    def from_settings(cls) -> OptimiseConfig:
        return cls(
            working_start=settings.working_day_start,
            working_end=settings.working_day_end,
            default_service_minutes=settings.default_service_minutes,
            skip_weekdays=settings.skip_weekday_set,
            near_limit_seconds=settings.near_limit_minutes * 60,
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
) -> OptimiseResult:
    config = config or OptimiseConfig.from_settings()
    matrix_provider = matrix_provider or _osrm_matrix
    vroom_client = vroom_client or VroomClient()

    days = working_days(tour, config)

    stops = list(
        db.scalars(
            select(Stop).where(
                Stop.tour_id == tour.id,
                Stop.status == "confirmed",
                Stop.status_hint != "skip",
            )
        )
    )

    # Fresh run: clear any previous assignment so unassigned stops end up null.
    for stop in stops:
        stop.assigned_day = None
        stop.sequence = None
        stop.eta = None

    coords_by_id = _coords_by_id(db, [s.id for s in stops])

    schedulable: list[_Job] = []
    unassigned: list[UnassignedStop] = []

    for stop in stops:
        if stop.id not in coords_by_id:
            unassigned.append(
                UnassignedStop(stop_id=stop.id, reason=REASON_MISSING_LOCATION)
            )
            continue

        service = (stop.service_minutes or config.default_service_minutes) * 60
        windows = _job_windows(stop, days, service, config)
        if not windows:
            reason = REASON_NO_DAYS if not days else REASON_NO_WINDOW
            unassigned.append(UnassignedStop(stop_id=stop.id, reason=reason))
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

    problem = _build_problem(schedulable, days, config, matrix_provider)
    solution = vroom_client.solve(problem)

    stop_by_id = {job.stop.id: job.stop for job in schedulable}
    summaries = _apply_solution(solution, days, stop_by_id, config)

    for entry in solution.get("unassigned", []):
        unassigned.append(
            UnassignedStop(stop_id=int(entry["id"]), reason=REASON_NO_DAYS)
        )

    db.commit()
    return OptimiseResult(tour_id=tour.id, days=summaries, unassigned=unassigned)


@dataclass
class _Job:
    stop: Stop
    coord: Coordinate
    service: int
    windows: list[list[int]]


def _coords_by_id(db: Session, stop_ids: list[int]) -> dict[int, Coordinate]:
    if not stop_ids:
        return {}
    rows = db.execute(
        select(Stop.id, func.ST_X(Stop.geom), func.ST_Y(Stop.geom)).where(
            Stop.id.in_(stop_ids), Stop.geom.isnot(None)
        )
    ).all()
    return {sid: (lon, lat) for sid, lon, lat in rows}


def _job_windows(
    stop: Stop, days: list[date], service: int, config: OptimiseConfig
) -> list[list[int]]:
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
) -> dict:
    matrix = matrix_provider([job.coord for job in jobs])

    # Vroom requires every vehicle to have a start or end, so a truly depot-less
    # vehicle is rejected. We append a virtual depot with zero travel to/from
    # every job and use it as an open-ended start: leaving it costs nothing, so
    # it has no effect on the plan or on reported drive time.
    depot_index = len(matrix)
    matrix = [list(row) + [0] for row in matrix]
    matrix.append([0] * (depot_index + 1))

    vehicles = [
        {
            "id": index,
            "profile": "car",
            "start_index": depot_index,
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
