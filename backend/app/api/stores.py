from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_role, worker_services_store
from app.db import get_db
from app.models.stop import Stop
from app.models.store import Store
from app.models.tour import Tour
from app.models.user import Role, User
from app.models.visit_feedback import VisitFeedback
from app.schemas.feedback import FeedbackRead
from app.schemas.store import (
    StopSuggestion,
    StoreAttributesUpdate,
    StoreRead,
    StoreServiceTimeRead,
    StoreVisit,
)
from app.services.service_times import recompute_service_times

router = APIRouter(prefix="/stores", tags=["stores"])

_PLANNERS = Depends(require_role(Role.dispatcher, Role.admin))
_READERS = Depends(require_role(Role.manager, Role.dispatcher, Role.admin))


def _ensure_store_visible(db: Session, user: User, store_id: int) -> None:
    """Office roles see every store; workers only stores on their tours."""
    if user.role in (Role.manager, Role.dispatcher, Role.admin):
        return
    if worker_services_store(db, user, store_id):
        return
    raise HTTPException(status_code=403, detail="Store is not on your tours")


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
        learned_service_minutes=store.learned_service_minutes,
        service_time_samples=store.service_time_samples,
        service_times_updated_at=store.service_times_updated_at,
        size=store.size,
        in_mall=store.in_mall,
        has_parking=store.has_parking,
        attributes_updated_at=store.attributes_updated_at,
        attributes_updated_by=store.attributes_updated_by,
        attributes_complete=store.attributes_complete,
    )


@router.get("", response_model=list[StoreRead], dependencies=[_READERS])
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


@router.get("/suggest", response_model=list[StopSuggestion], dependencies=[_READERS])
def suggest_stops(
    db: Annotated[Session, Depends(get_db)],
    q: Annotated[str, Query(min_length=2, max_length=80)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> list[StopSuggestion]:
    """Type-ahead for the draft editor: match the typed text against store
    names/aliases/addresses in the catalog, then against stops of previous
    tours that never matched a catalog store. Catalog hits come first — they
    carry the canonical address and default tasks/minutes."""
    pattern = f"%{q.strip()}%"

    suggestions: list[StopSuggestion] = []
    for store in db.scalars(
        select(Store)
        .where(
            or_(
                Store.name.ilike(pattern),
                Store.street.ilike(pattern),
                Store.city.ilike(pattern),
                Store.aliases.cast(String).ilike(pattern),
            )
        )
        .order_by(Store.name)
        .limit(limit)
    ):
        suggestions.append(
            StopSuggestion(
                name=store.name,
                street=store.street,
                postal_code=store.postal_code,
                city=store.city,
                service_minutes=store.learned_service_minutes
                or store.default_service_minutes,
                tasks=", ".join(store.default_tasks) if store.default_tasks else None,
                source="catalog",
            )
        )

    room = limit - len(suggestions)
    if room > 0:
        seen = {
            (s.name.lower(), (s.street or "").lower(), s.postal_code or "")
            for s in suggestions
        }
        rows = db.execute(
            select(Stop.customer, Stop.street, Stop.postal_code, Stop.city)
            .where(
                Stop.store_id.is_(None),
                Stop.customer.isnot(None),
                or_(
                    Stop.customer.ilike(pattern),
                    Stop.street.ilike(pattern),
                    Stop.city.ilike(pattern),
                ),
            )
            .distinct()
            .order_by(Stop.customer)
            .limit(room * 3)
        ).all()
        for customer, street, postal_code, city in rows:
            key = (customer.lower(), (street or "").lower(), postal_code or "")
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(
                StopSuggestion(
                    name=customer,
                    street=street,
                    postal_code=postal_code,
                    city=city,
                    service_minutes=None,
                    tasks=None,
                    source="history",
                )
            )
            if len(suggestions) >= limit:
                break

    return suggestions


@router.post(
    "/service-times/recompute",
    response_model=list[StoreServiceTimeRead],
    dependencies=[_PLANNERS],
)
def recompute_store_service_times(
    db: Annotated[Session, Depends(get_db)],
) -> list[StoreServiceTimeRead]:
    """Re-learn every store's service duration from completion history (P4).

    Recomputes from scratch on each call — history is small — and needs OSRM
    for the drive legs between completed stops. Triggered from the office's
    stores page; new tours pick the learned values up at extraction time."""
    return [
        StoreServiceTimeRead(
            store_id=entry.store_id,
            name=entry.name,
            samples=entry.samples,
            learned_service_minutes=entry.learned_service_minutes,
        )
        for entry in recompute_service_times(db)
    ]


@router.get("/{store_id}", response_model=StoreRead)
def get_store(
    store_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> StoreRead:
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")
    _ensure_store_visible(db, user, store_id)
    return _store_read(db, store)


@router.get(
    "/{store_id}/visits", response_model=list[StoreVisit], dependencies=[_READERS]
)
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
    user: CurrentUser,
) -> list[VisitFeedback]:
    """The store's full visit-feedback history, newest first (mobile detail
    view + dashboard). Feedback is append-only — no edit/delete anywhere; a
    wrong store *fact* is fixed via PATCH /stores/{id}/attributes instead."""
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="store not found")
    _ensure_store_visible(db, user, store_id)
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
    user: CurrentUser,
) -> StoreRead:
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="store not found")

    # Crowdsourcing: dispatchers/admins anywhere, workers only for stores on
    # their own tours. Managers are read-only.
    if user.role not in (Role.dispatcher, Role.admin) and not (
        user.role == Role.worker and worker_services_store(db, user, store_id)
    ):
        raise HTTPException(status_code=403, detail="Store is not on your tours")

    fields = payload.model_dump(exclude_unset=True)
    if not _ATTRIBUTE_FIELDS & fields.keys():
        raise HTTPException(status_code=422, detail="no attributes provided")

    for key, value in fields.items():
        if key in _ATTRIBUTE_FIELDS:
            setattr(store, key, value)
    store.attributes_updated_at = func.now()
    # The authenticated identity is the audit trail; the free-text payload
    # field is legacy from before auth existed.
    store.attributes_updated_by = user.name

    db.commit()
    db.refresh(store)
    return _store_read(db, store)
