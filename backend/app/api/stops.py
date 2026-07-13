from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.db import get_db
from app.models.stop import HoursSource, Stop
from app.schemas.stop import (
    StopCompleteRequest,
    StopPlanUpdate,
    StopRead,
    StopUpdate,
)
from app.services.optimiser import move_stop

router = APIRouter(prefix="/stops", tags=["stops"])


@router.patch("/{stop_id}", response_model=StopRead)
def update_stop(
    stop_id: int,
    payload: StopUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> Stop:
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")

    fields = payload.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(stop, key, value)

    # closing_time is feasibility-critical: a manual closing time always wins,
    # so committing a tour later will not overwrite it.
    if fields.get("closing_time") is not None:
        stop.hours_source = HoursSource.manual

    db.commit()
    db.refresh(stop)
    return stop


@router.patch("/{stop_id}/plan", response_model=StopRead)
def update_stop_plan(
    stop_id: int,
    payload: StopPlanUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> Stop:
    """Manually move a stop to another day (or off the plan entirely).

    The edit is authoritative: it survives map reloads because clients read
    GET /tours/{id}/plan, which never re-solves. Both affected days are
    re-sequenced; the moved stop's ETA clears until the next optimise run.
    """
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")

    if payload.assigned_day is not None:
        tour = stop.tour
        if not (tour.date_from <= payload.assigned_day <= tour.date_to):
            raise HTTPException(
                status_code=422,
                detail="assigned_day is outside the tour's date range",
            )

    move_stop(db, stop, payload.assigned_day, payload.position)
    db.refresh(stop)
    return stop


@router.post("/{stop_id}/complete", response_model=StopRead)
def complete_stop(
    stop_id: int,
    db: Annotated[Session, Depends(get_db)],
    payload: StopCompleteRequest | None = None,
) -> Stop:
    """Mark a stop done. Idempotent: a repeat call (e.g. an offline-sync
    retry) keeps the original completed_at unless force is set."""
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")

    if stop.completed_at is None or (payload is not None and payload.force):
        stop.completed_at = func.now()
        db.commit()
        db.refresh(stop)
    return stop


@router.delete("/{stop_id}/complete", response_model=StopRead)
def uncomplete_stop(
    stop_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> Stop:
    """Undo a mis-tapped completion: clear completed_at. Idempotent."""
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")

    if stop.completed_at is not None:
        stop.completed_at = None
        db.commit()
        db.refresh(stop)
    return stop
