from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.stop import Stop
from app.models.visit_feedback import VisitFeedback
from app.schemas.feedback import FeedbackCreate, FeedbackRead

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackRead, status_code=status.HTTP_201_CREATED)
def create_feedback(
    payload: FeedbackCreate,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> VisitFeedback:
    """Record after-visit feedback. Idempotent on client_uuid: an offline-sync
    retry of an already-stored POST returns the existing row (200, not 201)."""
    existing = db.scalar(
        select(VisitFeedback).where(VisitFeedback.client_uuid == payload.client_uuid)
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing

    stop = db.get(Stop, payload.stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")

    feedback = VisitFeedback(
        stop_id=stop.id,
        tour_id=stop.tour_id,
        store_id=stop.store_id,
        employee=payload.employee,
        tags=[tag.value for tag in payload.tags],
        note=payload.note,
        photo_path=payload.photo_path,
        client_uuid=payload.client_uuid,
    )
    db.add(feedback)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent retry won the unique(client_uuid) race; serve its row.
        db.rollback()
        response.status_code = status.HTTP_200_OK
        return db.execute(
            select(VisitFeedback).where(
                VisitFeedback.client_uuid == payload.client_uuid
            )
        ).scalar_one()
    db.refresh(feedback)
    return feedback


@router.get("", response_model=list[FeedbackRead])
def list_feedback(
    db: Annotated[Session, Depends(get_db)],
    store_id: int | None = None,
    tour_id: int | None = None,
    stop_id: int | None = None,
) -> list[VisitFeedback]:
    """List feedback, newest first, optionally filtered. Feedback is
    append-only: there are deliberately no update/delete endpoints."""
    query = select(VisitFeedback)
    if store_id is not None:
        query = query.where(VisitFeedback.store_id == store_id)
    if tour_id is not None:
        query = query.where(VisitFeedback.tour_id == tour_id)
    if stop_id is not None:
        query = query.where(VisitFeedback.stop_id == stop_id)
    query = query.order_by(VisitFeedback.created_at.desc(), VisitFeedback.id.desc())
    return list(db.scalars(query).all())
