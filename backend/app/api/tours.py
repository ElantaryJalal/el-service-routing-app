from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.db import get_db
from app.models.stop import HoursSource, Stop
from app.models.task import Task
from app.models.tour import Tour
from app.schemas.draft import DraftStop, DraftStopUpdate, TourDraft
from app.schemas.optimise import OptimiseResult
from app.schemas.stop import CommitResult, StopDetail
from app.services.extraction import extract_tour, normalize_media_type
from app.services.extraction_local import extract_tour_local
from app.services.extraction_ollama import extract_tour_ollama
from app.services.geocoding import geocode_address
from app.services.opening_hours import fetch_opening_hours
from app.services.optimiser import optimise_tour
from app.services.store_catalog import enrich_stop_from_store, match_store

router = APIRouter(prefix="/tours", tags=["tours"])

# Stops accept a manual service-time in this range (mirrors StopUpdate/mobile).
_SERVICE_MIN, _SERVICE_MAX = 30, 600
_STATUS_HINTS = {"pending", "done", "rework", "skip", "unknown"}


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except (ValueError, AttributeError):
        return None


def _clamp_minutes(value: int | None) -> int | None:
    if value is None:
        return None
    return max(_SERVICE_MIN, min(_SERVICE_MAX, int(value)))


def _draft_stop(stop: Stop) -> DraftStop:
    labels = [task.raw_label or task.task_type for task in stop.tasks]
    confidence = {
        key: float(val)
        for key, val in (stop.confidence or {}).items()
        if isinstance(val, (int, float))
    }
    return DraftStop(
        id=stop.id,
        street=stop.street,
        postal_code=stop.postal_code,
        city=stop.city,
        order_no=stop.order_no,
        tasks=", ".join(labels) if labels else None,
        service_minutes=stop.service_minutes,
        confidence=confidence,
    )


def _build_draft(db: Session, tour_id: int) -> TourDraft:
    stops = db.scalars(
        select(Stop)
        .where(Stop.tour_id == tour_id)
        .options(selectinload(Stop.tasks))
        .order_by(Stop.row_index)
    ).all()
    return TourDraft(tour_id=tour_id, stops=[_draft_stop(s) for s in stops])


@router.post("/extract", response_model=TourDraft)
def extract(
    db: Annotated[Session, Depends(get_db)],
    image: Annotated[UploadFile, File()],
) -> TourDraft:
    """Extract a draft tour from a photographed plan (vision) and geocode it.

    Runs Claude vision extraction, persists a draft tour + stops (status
    ``draft``/``unconfirmed``) preserving row order, geocodes each stop
    best-effort (cached Nominatim), and returns the draft for the Confirm
    screen. Runs in a threadpool (sync def), so the multi-second model call
    doesn't block the event loop.
    """
    data = image.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty image")

    media_type = normalize_media_type(image.content_type, image.filename)
    try:
        if settings.extraction_provider == "local":
            parsed = extract_tour_local(db, data, media_type)
        elif settings.extraction_provider == "ollama":
            parsed = extract_tour_ollama(data, media_type)
        else:
            parsed = extract_tour(data, media_type)
    except Exception as exc:  # noqa: BLE001 — surface any extraction failure as 502
        raise HTTPException(
            status_code=502, detail=f"extraction failed: {exc}"
        ) from exc

    tour = Tour(
        customer=(parsed.customer or "Unknown").strip() or "Unknown",
        calendar_week=parsed.calendar_week or 0,
        date_from=_parse_iso_date(parsed.date_from) or date.today(),
        date_to=_parse_iso_date(parsed.date_to) or date.today(),
        team_lead=parsed.team_lead,
        employee=parsed.employee,
        vehicle=parsed.vehicle,
        status="draft",
    )
    db.add(tour)
    db.flush()

    for index, extracted in enumerate(parsed.stops):
        status_hint = extracted.status_hint or "unknown"
        stop = Stop(
            tour_id=tour.id,
            row_index=index,
            date=_parse_iso_date(extracted.date),
            weekday=extracted.weekday,
            customer=extracted.customer,
            order_no=extracted.order_no,
            street=extracted.street,
            postal_code=extracted.postal_code,
            city=extracted.city,
            remarks_raw=extracted.remarks,
            status_hint=status_hint if status_hint in _STATUS_HINTS else "unknown",
            service_minutes=_clamp_minutes(extracted.service_minutes),
            confidence=extracted.confidence.model_dump(exclude_none=True) or None,
            status="unconfirmed",
        )
        for label in extracted.tasks:
            label = (label or "").strip()
            if label:
                stop.tasks.append(Task(task_type=label, raw_label=label))

        # Known store? Take its canonical address/coordinate/tasks and skip
        # geocoding. Otherwise fall back to geocoding the extracted address.
        store = match_store(
            db, extracted.customer, extracted.city, extracted.postal_code
        )
        if store is not None:
            enrich_stop_from_store(stop, store)
        else:
            coords = geocode_address(
                db, extracted.street, extracted.postal_code, extracted.city
            )
            if coords is not None:
                lon, lat = coords
                stop.geom = WKTElement(f"POINT({lon} {lat})", srid=4326)
        db.add(stop)

    db.commit()
    return _build_draft(db, tour.id)


@router.get("/{tour_id}/draft", response_model=TourDraft)
def get_draft(
    tour_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> TourDraft:
    """The current draft (pre-commit) tour, for a reloaded/deep-linked Confirm."""
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")
    return _build_draft(db, tour_id)


@router.patch("/{tour_id}/draft/stops/{stop_id}", response_model=DraftStop)
def patch_draft_stop(
    tour_id: int,
    stop_id: int,
    update: DraftStopUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> DraftStop:
    """Apply the user's corrections to one draft stop.

    Only explicitly-set fields change. Editing a field clears its
    low-confidence flag; changing any address field re-geocodes the stop so the
    map stays correct after corrections.
    """
    stop = db.get(Stop, stop_id)
    if stop is None or stop.tour_id != tour_id:
        raise HTTPException(status_code=404, detail="draft stop not found")

    data = update.model_dump()
    confidence = dict(stop.confidence or {})
    address_changed = False

    for field in update.model_fields_set:
        value = data[field]
        if field == "tasks":
            stop.tasks.clear()  # delete-orphan cascade removes the old rows
            labels = (
                [part.strip() for part in value.split(",") if part.strip()]
                if value
                else []
            )
            for label in labels:
                stop.tasks.append(Task(task_type=label, raw_label=label))
        else:
            setattr(stop, field, value)
            if field in ("street", "postal_code", "city"):
                address_changed = True
        confidence.pop(field, None)

    stop.confidence = confidence or None

    if address_changed:
        coords = geocode_address(db, stop.street, stop.postal_code, stop.city)
        stop.geom = (
            WKTElement(f"POINT({coords[0]} {coords[1]})", srid=4326)
            if coords is not None
            else None
        )

    db.commit()
    db.refresh(stop, attribute_names=["tasks"])
    return _draft_stop(stop)


@router.get("/{tour_id}/stops", response_model=list[StopDetail])
def list_stops(
    tour_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> list[StopDetail]:
    """Committed stops with address, task labels, and geocoded coordinate.

    Returns every stop of the tour (including ungeocoded/unassigned ones, whose
    lat/lng are null) in the tour plan's original row order. Powers the mobile
    Review (edit hours) and Map (markers + detail) screens.
    """
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")

    stops = db.scalars(
        select(Stop)
        .where(Stop.tour_id == tour_id)
        .options(selectinload(Stop.tasks))
        .order_by(Stop.row_index)
    ).all()

    # One query for every coordinate; ungeocoded stops are simply absent.
    coords = {
        sid: (lon, lat)
        for sid, lon, lat in db.execute(
            select(Stop.id, func.ST_X(Stop.geom), func.ST_Y(Stop.geom)).where(
                Stop.tour_id == tour_id, Stop.geom.isnot(None)
            )
        ).all()
    }

    result: list[StopDetail] = []
    for stop in stops:
        lon, lat = coords.get(stop.id, (None, None))
        labels = [task.raw_label or task.task_type for task in stop.tasks]
        result.append(
            StopDetail(
                id=stop.id,
                tour_id=stop.tour_id,
                customer=stop.customer,
                opening_time=stop.opening_time,
                closing_time=stop.closing_time,
                service_minutes=stop.service_minutes,
                hours_source=stop.hours_source,
                status=stop.status,
                street=stop.street,
                postal_code=stop.postal_code,
                city=stop.city,
                tasks=", ".join(labels) if labels else None,
                lat=lat,
                lng=lon,
            )
        )
    return result


@router.post("/{tour_id}/commit", response_model=CommitResult)
def commit_tour(
    tour_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> CommitResult:
    """Confirm a tour and best-effort enrich stop opening hours from OSM.

    Geocoding is assumed to have run already (stops carry a geom). Only stops
    whose hours are still unknown (hours_source='default') are looked up, so
    manual and previously-fetched OSM hours are never overwritten.
    """
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")

    stops = db.scalars(select(Stop).where(Stop.tour_id == tour_id)).all()

    enriched = 0
    for stop in stops:
        # Committing the tour confirms its stops (extract leaves them
        # 'unconfirmed'); a stop already marked 'done' keeps its status.
        if stop.status != "done":
            stop.status = "confirmed"

        if stop.geom is None or stop.hours_source != HoursSource.default:
            continue

        lon, lat = db.execute(
            select(func.ST_X(Stop.geom), func.ST_Y(Stop.geom)).where(Stop.id == stop.id)
        ).one()

        try:
            window = fetch_opening_hours(lon, lat)
        except Exception:
            # Best-effort: never fail commit on an Overpass hiccup.
            window = None

        if window is not None:
            stop.opening_time, stop.closing_time = window
            stop.hours_source = HoursSource.osm
            enriched += 1

    tour.status = "confirmed"
    db.commit()

    return CommitResult(
        tour_id=tour_id,
        status=tour.status,
        stops_total=len(stops),
        stops_enriched=enriched,
    )


@router.post("/{tour_id}/optimise", response_model=OptimiseResult)
def optimise(
    tour_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> OptimiseResult:
    """Assign every confirmed market to a working day and order it."""
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")
    return optimise_tour(db, tour)
