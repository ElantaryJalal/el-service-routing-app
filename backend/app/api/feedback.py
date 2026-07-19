from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import CurrentUser, ensure_tour_workable, require_role
from app.config import settings
from app.db import get_db
from app.models.stop import Stop
from app.models.user import Role
from app.models.visit_feedback import VisitFeedback, dedupe_feedback
from app.schemas.feedback import FeedbackCreate, FeedbackRead, PhotoUploadResult

router = APIRouter(prefix="/feedback", tags=["feedback"])

# Feedback is written by the field and the office, never by read-only managers.
_WRITERS = Depends(require_role(Role.worker, Role.dispatcher, Role.admin))
_READERS = Depends(require_role(Role.manager, Role.dispatcher, Role.admin))

_PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_PHOTO_MAX_BYTES = 10 * 1024 * 1024


@router.post("/photos", response_model=PhotoUploadResult, dependencies=[_WRITERS])
def upload_feedback_photo(
    image: Annotated[UploadFile, File()],
) -> PhotoUploadResult:
    """Store a feedback photo; the returned photo_path goes into POST
    /feedback. Uploaded separately so the feedback body itself stays a small
    JSON document the offline outbox can park and replay."""
    ext = _PHOTO_TYPES.get(image.content_type or "")
    if ext is None:
        raise HTTPException(status_code=415, detail="unsupported image type")
    data = image.file.read(_PHOTO_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="empty image")
    if len(data) > _PHOTO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="image too large")

    folder = Path(settings.media_dir) / "feedback"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid4().hex}{ext}"
    (folder / name).write_bytes(data)
    return PhotoUploadResult(photo_path=f"media/feedback/{name}")


@router.post("", response_model=FeedbackRead, status_code=status.HTTP_201_CREATED)
def create_feedback(
    payload: FeedbackCreate,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
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
    ensure_tour_workable(user, stop.tour)

    feedback = VisitFeedback(
        stop_id=stop.id,
        tour_id=stop.tour_id,
        store_id=stop.store_id,
        # The authenticated identity wins; the payload field predates auth.
        employee=user.name,
        tags=[tag.value for tag in payload.tags],
        note=payload.note,
        photo_path=payload.photo_path,
        client_uuid=payload.client_uuid,
        # Test/demo accounts live on the e2e domain; anything they write (and
        # anything on a demo tour) must never surface to management.
        is_demo=user.email.endswith("@e2e.elservice.de") or stop.is_demo,
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


@router.get("", response_model=list[FeedbackRead], dependencies=[_READERS])
def list_feedback(
    db: Annotated[Session, Depends(get_db)],
    store_id: int | None = None,
    tour_id: int | None = None,
    stop_id: int | None = None,
    include_demo: bool = False,
) -> list[VisitFeedback]:
    """List feedback, newest first, optionally filtered. Feedback is
    append-only: there are deliberately no update/delete endpoints.

    Demo/seeded rows are excluded unless include_demo is set, and exact
    duplicates (same store, author, note, and timestamp — offline-sync and
    seed artefacts) collapse to a single entry.
    """
    query = select(VisitFeedback).options(selectinload(VisitFeedback.store))
    if store_id is not None:
        query = query.where(VisitFeedback.store_id == store_id)
    if tour_id is not None:
        query = query.where(VisitFeedback.tour_id == tour_id)
    if stop_id is not None:
        query = query.where(VisitFeedback.stop_id == stop_id)
    if not include_demo:
        query = query.where(VisitFeedback.is_demo.is_(False))
    query = query.order_by(VisitFeedback.created_at.desc(), VisitFeedback.id.desc())
    return dedupe_feedback(db.scalars(query))
