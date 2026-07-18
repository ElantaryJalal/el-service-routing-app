"""Read-only reporting for the executive dashboard.

Aggregates are framed as *work completed* (tours, stops, punctuality), never
per-worker performance — this is the direction's overview, not surveillance.
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_role
from app.db import get_db
from app.models.stop import Stop
from app.models.tour import Tour, TourStatus
from app.models.user import Role
from app.schemas.reports import (
    DayLoad,
    OnTimeStats,
    OutstandingStop,
    OverviewReport,
    TourCounts,
)

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(require_role(Role.manager, Role.dispatcher, Role.admin))],
)


def _current_week() -> tuple[date, date]:
    """Monday–Sunday of the current ISO week."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


@router.get("/overview", response_model=OverviewReport)
def overview(
    db: Annotated[Session, Depends(get_db)],
    date_from: date | None = None,
    date_to: date | None = None,
    tolerance_minutes: Annotated[int, Query(ge=0, le=240)] = 30,
) -> OverviewReport:
    """This-week snapshot: tour/stop completion counts, per-day load,
    punctuality vs. predicted ETA, and the markets still outstanding.

    Defaults to the current ISO week; pass date_from/date_to for another
    range. A tour is in scope when its dates overlap the range; draft tours
    count in the tour breakdown but their (unconfirmed) stops are excluded
    from the work KPIs.
    """
    if (date_from is None) != (date_to is None):
        raise HTTPException(
            status_code=422, detail="date_from and date_to must be given together"
        )
    if date_from is None or date_to is None:
        date_from, date_to = _current_week()
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="date_to is before date_from")
    if (date_to - date_from).days > 31:
        raise HTTPException(status_code=422, detail="range is limited to 31 days")

    tours = list(
        db.scalars(
            select(Tour).where(Tour.date_from <= date_to, Tour.date_to >= date_from)
        )
    )
    by_status = {status: 0 for status in TourStatus}
    for tour in tours:
        by_status[tour.status] += 1

    work_tour_ids = [t.id for t in tours if t.status != TourStatus.draft]
    stops: list[Stop] = (
        list(
            db.scalars(
                select(Stop).where(Stop.tour_id.in_(work_tour_ids))
                # effective_city reads through to the store (outstanding list).
                .options(selectinload(Stop.store))
            )
        )
        if work_tour_ids
        else []
    )

    completed = [s for s in stops if s.completed_at is not None]

    days: list[DayLoad] = []
    day = date_from
    while day <= date_to:
        days.append(
            DayLoad(
                day=day,
                planned=sum(1 for s in stops if s.assigned_day == day),
                completed=sum(1 for s in completed if s.completed_at.date() == day),
            )
        )
        day += timedelta(days=1)

    timed = [s for s in completed if s.eta is not None]
    deltas = [
        (s.completed_at - s.eta).total_seconds() / 60
        for s in timed
        if s.completed_at.tzinfo is not None and s.eta.tzinfo is not None
    ]
    on_time_count = sum(1 for d in deltas if d <= tolerance_minutes)
    on_time = OnTimeStats(
        sample_count=len(deltas),
        on_time_count=on_time_count,
        on_time_rate=round(on_time_count / len(deltas), 3) if deltas else None,
        average_delta_minutes=round(sum(deltas) / len(deltas), 1) if deltas else None,
        tolerance_minutes=tolerance_minutes,
    )

    outstanding = sorted(
        (s for s in stops if s.completed_at is None),
        key=lambda s: (s.assigned_day or date.max, s.sequence or 0, s.id),
    )

    return OverviewReport(
        date_from=date_from,
        date_to=date_to,
        tours=TourCounts(
            total=len(tours),
            draft=by_status[TourStatus.draft],
            planned=by_status[TourStatus.planned],
            assigned=by_status[TourStatus.assigned],
            in_progress=by_status[TourStatus.in_progress],
            done=by_status[TourStatus.done],
        ),
        stops_planned=len(stops),
        stops_completed=len(completed),
        days=days,
        on_time=on_time,
        outstanding=[
            OutstandingStop(
                stop_id=s.id,
                tour_id=s.tour_id,
                customer=s.customer,
                city=s.effective_city,
                assigned_day=s.assigned_day,
                eta=s.eta,
            )
            for s in outstanding
        ],
    )
