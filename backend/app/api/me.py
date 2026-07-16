"""Endpoints scoped to the authenticated user."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.api.deps import ACTIVE_TOUR_STATUSES, CurrentUser
from app.db import get_db
from app.models.push_token import PushToken
from app.models.tour import Tour
from app.schemas.push import PushTokenRegister
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


@router.post("/push-tokens", status_code=204)
def register_push_token(
    payload: PushTokenRegister,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Register this device's Expo push token for the caller. Idempotent; a
    token already registered to another user moves to the caller (a shared
    crew phone changing hands)."""
    row = db.scalar(select(PushToken).where(PushToken.token == payload.token))
    if row is None:
        row = PushToken(token=payload.token)
        db.add(row)
    row.user_id = user.id
    row.platform = payload.platform
    row.last_seen_at = func.now()
    db.commit()


@router.delete("/push-tokens", status_code=204)
def unregister_push_token(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str, Query(min_length=1, max_length=400)],
) -> None:
    """Forget the device token (called on sign-out, before the session is
    dropped). Only the caller's own registration is deleted."""
    db.execute(
        delete(PushToken).where(PushToken.token == token, PushToken.user_id == user.id)
    )
    db.commit()
