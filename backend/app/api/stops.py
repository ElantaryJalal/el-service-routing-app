from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, ensure_tour_workable, require_role
from app.db import get_db
from app.models.stop import Stop
from app.models.store import AddressProvenance, GeomProvenance, HoursSource
from app.models.tour import Tour, TourStatus
from app.models.user import Role, User
from app.schemas.stop import (
    ResolveAddressRequest,
    StopCompleteRequest,
    StopPlanUpdate,
    StopRead,
    StopUpdate,
)
from app.services.optimiser import move_stop
from app.services.store_resolution import claim_matches_store

router = APIRouter(prefix="/stops", tags=["stops"])

# Editing stops-as-plan is a planning operation.
_PLANNERS = Depends(require_role(Role.dispatcher, Role.admin))


def _refresh_tour_progress(db: Session, tour: Tour) -> None:
    """Move the tour along its lifecycle from stop completion state.

    First completed stop -> in_progress; every stop completed -> done;
    completions all undone -> back to assigned (or planned if nobody is
    assigned). Draft tours don't track progress.
    """
    if tour.status == TourStatus.draft:
        return

    total, completed = db.execute(
        select(
            func.count(Stop.id),
            func.count(Stop.completed_at),
        ).where(Stop.tour_id == tour.id)
    ).one()

    if completed == 0:
        if tour.status in (TourStatus.in_progress, TourStatus.done):
            tour.status = (
                TourStatus.assigned
                if tour.assigned_user_id is not None
                else TourStatus.planned
            )
    elif completed < total:
        tour.status = TourStatus.in_progress
    else:
        tour.status = TourStatus.done


@router.patch("/{stop_id}", response_model=StopRead, dependencies=[_PLANNERS])
def update_stop(
    stop_id: int,
    payload: StopUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> Stop:
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")

    fields = payload.model_dump(exclude_unset=True)
    hours_fields = {
        k: fields.pop(k) for k in ("opening_time", "closing_time") if k in fields
    }

    for key, value in fields.items():
        setattr(stop, key, value)

    # Hours are a property of the shop: they write through to the linked
    # store, so every future tour visiting it inherits the correction.
    if hours_fields:
        if stop.store is None:
            raise HTTPException(
                status_code=422,
                detail="stop has no linked store to hold opening hours"
                " — commit the tour to resolve it against the catalog first",
            )
        for key, value in hours_fields.items():
            setattr(stop.store, key, value)
        # closing_time is feasibility-critical: a manual closing time always
        # wins, so committing a tour later will not overwrite it.
        if hours_fields.get("closing_time") is not None:
            stop.store.hours_source = HoursSource.manual

    db.commit()
    db.refresh(stop)
    return stop


@router.patch("/{stop_id}/plan", response_model=StopRead)
def update_stop_plan(
    stop_id: int,
    payload: StopPlanUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> Stop:
    """Manually move a stop to another day (or off the plan entirely).

    Rescheduling a day is field-workable: dispatcher/admin on any tour, a
    worker only on their own active tour (managers stay read-only). The edit
    is authoritative: it survives map reloads because clients read
    GET /tours/{id}/plan, which never re-solves. Both affected days are
    re-sequenced; the moved stop's ETA clears until the next optimise run.
    """
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")
    ensure_tour_workable(user, stop.tour)

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


@router.delete("/{stop_id}", status_code=204, dependencies=[_PLANNERS])
def delete_stop(
    stop_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Remove a stop (e.g. a duplicate row flagged by commit). Feedback rows
    keep their history — their stop_id FK nulls out."""
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")
    db.delete(stop)
    db.commit()


@router.post("/{stop_id}/complete", response_model=StopRead)
def complete_stop(
    stop_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    payload: StopCompleteRequest | None = None,
) -> Stop:
    """Mark a stop done. Idempotent: a repeat call (e.g. an offline-sync
    retry) keeps the original completed_at unless force is set."""
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")
    ensure_tour_workable(user, stop.tour)

    if stop.completed_at is None or (payload is not None and payload.force):
        stop.completed_at = func.now()
        _confirm_store_location(stop, user)
        db.flush()
        _refresh_tour_progress(db, stop.tour)
        db.commit()
        db.refresh(stop)
    return stop


def _confirm_store_location(stop: Stop, user: User) -> None:
    """Completion is the strongest evidence we ever get: the worker physically
    stood at the store, so the pin was good enough to navigate to. Upgrade the
    store's geometry provenance to field-confirmed and refresh the stamp."""
    store = stop.store
    if store is None or store.geom is None:
        return
    store.geom_provenance = GeomProvenance.field_confirmed
    store.verified_at = func.now()
    store.verified_by = user.name


@router.post(
    "/{stop_id}/resolve-address", response_model=StopRead, dependencies=[_PLANNERS]
)
def resolve_address(
    stop_id: int,
    payload: ResolveAddressRequest,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> Stop:
    """Settle a "plan disagrees with store" row (address_matches_store=false).

    'keep_store': the verified store address stands — the review row is
    dismissed durably (survives re-commits); the claim is kept untouched as
    the audit trail. 'use_claim': the plan was right — the store's address is
    updated from the claim and marked verified by the dispatcher. Neither
    action ever edits claimed_*.
    """
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")
    if stop.store is None:
        raise HTTPException(status_code=422, detail="stop has no linked store")
    if stop.address_matches_store is not False:
        raise HTTPException(
            status_code=409, detail="stop has no address mismatch to resolve"
        )

    if payload.action == "use_claim":
        store = stop.store
        if stop.claimed_street:
            store.street = stop.claimed_street
        if stop.claimed_postal_code:
            store.postal_code = stop.claimed_postal_code
        if stop.claimed_city:
            store.city = stop.claimed_city
        store.address_provenance = AddressProvenance.verified
        store.verified_at = func.now()
        store.verified_by = user.name
        stop.address_matches_store = claim_matches_store(stop, store)

    stop.address_review_resolved_at = func.now()
    stop.address_review_resolved_by = user.name
    db.commit()
    db.refresh(stop)
    return stop


@router.delete("/{stop_id}/complete", response_model=StopRead)
def uncomplete_stop(
    stop_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> Stop:
    """Undo a mis-tapped completion: clear completed_at. Idempotent."""
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail="stop not found")
    ensure_tour_workable(user, stop.tour)

    if stop.completed_at is not None:
        stop.completed_at = None
        db.flush()
        _refresh_tour_progress(db, stop.tour)
        db.commit()
        db.refresh(stop)
    return stop
