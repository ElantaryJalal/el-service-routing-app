from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.stop import Stop
from app.models.store import Store
from app.models.tour import Tour
from app.models.visit_feedback import VisitFeedback
from app.schemas.feedback import FeedbackRead
from app.schemas.store import StoreAttributesUpdate, StoreRead, StoreVisit

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


@router.get("", response_model=list[StoreRead])
def list_stores(
    db: Annotated[Session, Depends(get_db)],
    needs_attributes: bool | None = None,
) -> list[StoreRead]:
    """The store catalog, A-Z, for the office view. needs_attributes=true
    filters to stores still missing a crowdsourced attribute (the "which
    facts are we lacking" list); false filters to complete ones."""
    query = select(Store).order_by(Store.name)
    missing = or_(
        Store.size.is_(None),
        Store.in_mall.is_(None),
        Store.has_parking.is_(None),
    )
    if needs_attributes is True:
        query = query.where(missing)
    elif needs_attributes is False:
        query = query.where(~missing)
    return [_store_read(db, store) for store in db.scalars(query)]


@router.get("/{store_id}", response_model=StoreRead)
def get_store(store_id: int, db: Annotated[Session, Depends(get_db)]) -> StoreRead:
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    return _store_read(db, store)


@router.get("/{store_id}/visits", response_model=list[StoreVisit])
def store_visits(
    store_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> list[StoreVisit]:
    """Every stop ever linked to this store, newest first — the office's
    visit history with predicted ETA vs. actual completion."""
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="store not found")

    rows = db.execute(
        select(Stop, Tour)
        .join(Tour, Stop.tour_id == Tour.id)
        .where(Stop.store_id == store_id)
        .order_by(
            func.coalesce(Stop.assigned_day, Stop.date).desc().nulls_last(),
            Stop.id.desc(),
        )
    ).all()

    return [
        StoreVisit(
            stop_id=stop.id,
            tour_id=tour.id,
            calendar_week=tour.calendar_week,
            date=stop.assigned_day or stop.date,
            employee=tour.employee or tour.team_lead,
            service_minutes=stop.service_minutes,
            eta=stop.eta,
            completed_at=stop.completed_at,
        )
        for stop, tour in rows
    ]


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
