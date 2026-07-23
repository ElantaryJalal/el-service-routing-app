"""Worker-initiated "add another stop" — pull the smartest feasible future
stop into today using real driving time.

The office plans the week; this lets a worker who finishes early pull a
later-day stop forward. Ranking is by real OSRM drive time from the worker's
current position (the thing the app knows and the worker doesn't), and only
stops that can actually be finished today — open at arrival, service done
before the store closes and within the working window — are offered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models.stop import Stop
from app.models.tour import Tour
from app.routing.osrm import OSRMClient
from app.services.geocoding import geocode_address
from app.services.optimiser import (
    Coordinate,
    OptimiseConfig,
    _coords_by_id,
    _last_completed_coord,
    service_minutes_map,
)
from app.services.scheduling import effective_window


@dataclass
class PullCandidate:
    stop_id: int
    store_name: str
    drive_seconds: int
    projected_arrival: time
    service_minutes: int


def _secs(t: time) -> int:
    return t.hour * 3600 + t.minute * 60 + t.second


def _time_from_secs(s: int) -> time:
    s = max(0, min(s, 24 * 3600 - 60))
    return time(s // 3600, (s % 3600) // 60)


def _eligible_stops(db: Session, tour_id: int, *, later_than: date) -> list[Stop]:
    """Unfinished, still-open stops assigned to a day after `later_than`."""
    return list(
        db.scalars(
            select(Stop)
            .where(
                Stop.tour_id == tour_id,
                Stop.status == "confirmed",
                Stop.status_hint != "skip",
                Stop.completed_at.is_(None),
                Stop.assigned_day.isnot(None),
                Stop.assigned_day > later_than,
            )
            .options(selectinload(Stop.store), selectinload(Stop.tasks))
        )
    )


def _stops_on_day(db: Session, tour_id: int, day: date) -> list[Stop]:
    return list(
        db.scalars(
            select(Stop)
            .where(
                Stop.tour_id == tour_id,
                Stop.status == "confirmed",
                Stop.status_hint != "skip",
                Stop.assigned_day == day,
            )
            .options(selectinload(Stop.store), selectinload(Stop.tasks))
        )
    )


def pull_candidates(
    db: Session,
    tour: Tour,
    from_lat: float,
    from_lng: float,
    day: date,
    *,
    now: datetime | None = None,
    limit: int = 3,
    config: OptimiseConfig | None = None,
    osrm: OSRMClient | None = None,
) -> list[PullCandidate]:
    """Top feasible later-day stops ranked by real drive time from (lat, lng)."""
    config = config or OptimiseConfig.from_settings()
    osrm = osrm or OSRMClient()
    now = now or datetime.now()

    stops = _eligible_stops(db, tour.id, later_than=day)
    coords = _coords_by_id(db, [s.id for s in stops])
    routable = [s for s in stops if s.id in coords]
    if not routable:
        return []

    from_coord: Coordinate = (from_lng, from_lat)  # OSRM order is (lon, lat)
    matrix = osrm.duration_matrix([from_coord, *(coords[s.id] for s in routable)])
    drive_row = matrix[0][1:]

    svc = service_minutes_map(db, routable, config)
    ws, we = _secs(config.working_start), _secs(config.working_end)
    # Earliest the worker can set off: now, but never before the working day.
    start = max(_secs(now.time()), ws)

    out: list[PullCandidate] = []
    for stop, drive in zip(routable, drive_row, strict=True):
        drive_s = int(drive)
        arrival = start + drive_s
        open_t, close_t = effective_window(
            stop, config.working_start, config.working_end
        )
        # effective_window already clamps close to the working-day end, so a
        # single "service finished by close" check enforces both rules.
        service_start = max(arrival, _secs(open_t))
        finish = service_start + svc[stop.id] * 60
        if arrival <= _secs(close_t) and finish <= _secs(close_t) and finish <= we:
            out.append(
                PullCandidate(
                    stop_id=stop.id,
                    store_name=(stop.store.name if stop.store else None)
                    or (stop.customer or f"Stop {stop.id}"),
                    drive_seconds=drive_s,
                    projected_arrival=_time_from_secs(arrival),
                    service_minutes=svc[stop.id],
                )
            )

    out.sort(key=lambda c: c.drive_seconds)
    return out[:limit]


def _route_from(
    start: Coordinate,
    stops: list[Stop],
    coords: dict[int, Coordinate],
    osrm: OSRMClient,
) -> list[tuple[Stop, int]]:
    """Nearest-neighbour order of `stops` from `start`, with the drive time (s)
    into each stop along the chosen route."""
    if not stops:
        return []
    points = [start, *(coords[s.id] for s in stops)]
    matrix = osrm.duration_matrix(points)
    remaining = list(range(1, len(points)))
    order: list[tuple[Stop, int]] = []
    current = 0
    while remaining:
        nxt = min(remaining, key=lambda j: matrix[current][j])
        order.append((stops[nxt - 1], int(matrix[current][nxt])))
        remaining.remove(nxt)
        current = nxt
    return order


def _day_start(
    db: Session,
    tour: Tour,
    completed_today: list[Stop],
    coords: dict[int, Coordinate],
    config: OptimiseConfig,
    now: datetime,
) -> tuple[Coordinate | None, int]:
    """Where and when the remaining route resumes: after the last completed
    stop (today, else anywhere on the tour), else the company base at the
    start of the working day."""
    if completed_today:
        last = completed_today[-1]
        if last.id in coords:
            at = last.eta.time() if last.eta is not None else now.time()
            return coords[last.id], max(_secs(at), _secs(config.working_start))
    depot = _last_completed_coord(db, tour.id) or geocode_address(
        db,
        settings.default_start_street,
        settings.default_start_postal_code,
        settings.default_start_city,
    )
    return depot, max(_secs(now.time()), _secs(config.working_start))


def pull_into_today(
    db: Session,
    tour: Tour,
    stop: Stop,
    day: date,
    *,
    now: datetime | None = None,
    config: OptimiseConfig | None = None,
    osrm: OSRMClient | None = None,
) -> None:
    """Move `stop` to `day`, then re-sequence and re-time that day's remaining
    route from the worker's last position. Idempotent: safe to retry."""
    config = config or OptimiseConfig.from_settings()
    osrm = osrm or OSRMClient()
    now = now or datetime.now()

    stop.assigned_day = day
    stop.unassigned_reason = None
    db.flush()

    day_stops = _stops_on_day(db, tour.id, day)
    completed = sorted(
        (s for s in day_stops if s.completed_at is not None),
        key=lambda s: s.completed_at,
    )
    unfinished = [s for s in day_stops if s.completed_at is None]
    coords = _coords_by_id(db, [s.id for s in day_stops])

    routable = [s for s in unfinished if s.id in coords]
    non_routable = [s for s in unfinished if s.id not in coords]

    # Completed stops keep their place at the front of the day.
    seq = 1
    for s in completed:
        s.sequence = seq
        seq += 1

    start_coord, start_secs = _day_start(db, tour, completed, coords, config, now)
    ordered = (
        _route_from(start_coord, routable, coords, osrm)
        if start_coord is not None
        else [(s, 0) for s in routable]
    )

    svc = service_minutes_map(db, routable, config)
    cursor = start_secs
    for member, drive in ordered:
        arrival = cursor + drive
        open_t, close_t = effective_window(
            member, config.working_start, config.working_end
        )
        member.sequence = seq
        seq += 1
        member.eta = datetime.combine(day, _time_from_secs(arrival), tzinfo=UTC)
        service_start = max(arrival, _secs(open_t))
        cursor = service_start + svc[member.id] * 60

    for s in non_routable:
        s.sequence = seq
        seq += 1
        s.eta = None

    db.commit()
