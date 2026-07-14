"""Endpoints scoped to the authenticated user."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ACTIVE_TOUR_STATUSES, CurrentUser
from app.db import get_db
from app.models.tour import Tour
from app.schemas.tour import TourRead

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/tours", response_model=list[TourRead])
def my_tours(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[Tour]:
    """The caller's current workload: tours assigned to them that are still
    assigned/in_progress. This is the worker's home-screen list."""
    return list(
        db.scalars(
            select(Tour)
            .where(
                Tour.assigned_user_id == user.id,
                Tour.status.in_(ACTIVE_TOUR_STATUSES),
            )
            .order_by(Tour.date_from, Tour.id)
        )
    )
