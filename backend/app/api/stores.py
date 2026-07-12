from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.store import Store
from app.models.visit_feedback import VisitFeedback
from app.schemas.feedback import FeedbackRead
from app.schemas.store import StoreAttributesUpdate, StoreRead

router = APIRouter(prefix="/stores", tags=["stores"])

# The three crowdsourced attributes; updated_by is audit metadata, not one of
# them, so it alone must not bump attributes_updated_at.
_ATTRIBUTE_FIELDS = {"size", "in_mall", "has_parking"}


def _store_read(db: Session, store: Store) -> StoreRead:
    lon, lat = (None, None)
    if store.geom is not None:
        lon, lat = db.execute(
            select(func.ST_X(Store.geom), func.ST_Y(Store.geom)).where(
                Store.id == store.id
            )
        ).one()
    return StoreRead(
        id=store.id,
        name=store.name,
        street=store.street,
        postal_code=store.postal_code,
        city=store.city,
        lat=lat,
        lng=lon,
        default_tasks=store.default_tasks,
        default_service_minutes=store.default_service_minutes,
        size=store.size,
        in_mall=store.in_mall,
        has_parking=store.has_parking,
        attributes_updated_at=store.attributes_updated_at,
        attributes_updated_by=store.attributes_updated_by,
        attributes_complete=store.attributes_complete,
    )


@router.get("/{store_id}", response_model=StoreRead)
def get_store(store_id: int, db: Annotated[Session, Depends(get_db)]) -> StoreRead:
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    return _store_read(db, store)


@router.get("/{store_id}/feedback", response_model=list[FeedbackRead])
def store_feedback(
    store_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> list[VisitFeedback]:
    """The store's full visit-feedback history, newest first (mobile detail
    view + dashboard). Feedback is append-only — no edit/delete anywhere; a
    wrong store *fact* is fixed via PATCH /stores/{id}/attributes instead."""
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="store not found")
    return list(
        db.scalars(
            select(VisitFeedback)
            .where(VisitFeedback.store_id == store_id)
            .order_by(VisitFeedback.created_at.desc(), VisitFeedback.id.desc())
        )
    )


@router.patch("/{store_id}/attributes", response_model=StoreRead)
def update_store_attributes(
    store_id: int,
    payload: StoreAttributesUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> StoreRead:
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")

    fields = payload.model_dump(exclude_unset=True)
    if not _ATTRIBUTE_FIELDS & fields.keys():
        raise HTTPException(status_code=422, detail="no attributes provided")

    for key, value in fields.items():
        if key in _ATTRIBUTE_FIELDS:
            setattr(store, key, value)
    store.attributes_updated_at = func.now()
    store.attributes_updated_by = fields.get("updated_by")

    db.commit()
    db.refresh(store)
    return _store_read(db, store)
