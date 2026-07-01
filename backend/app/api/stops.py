from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.stop import HoursSource, Stop
from app.schemas.stop import StopRead, StopUpdate

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
