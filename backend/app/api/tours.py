from datetime import date
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import CurrentUser, ensure_tour_visible, require_role
from app.config import settings
from app.db import get_db
from app.models.stop import Stop
from app.models.store import HoursSource, Store
from app.models.task import Task
from app.models.tour import Tour, TourStatus
from app.models.user import Role, User
from app.models.visit_feedback import VisitFeedback
from app.schemas.draft import DraftStop, DraftStopCreate, DraftStopUpdate, TourDraft
from app.schemas.optimise import OptimiseRequest, OptimiseResult
from app.schemas.stop import (
    AddressMismatchRead,
    CommitResult,
    MatchCandidateRead,
    MatchReviewItem,
    NewStoreRead,
    StopDetail,
)
from app.schemas.tour import TourAssignRequest, TourCreate, TourRead, TourUpdate
from app.services.extraction import extract_tour, normalize_media_type
from app.services.extraction_local import extract_tour_local
from app.services.extraction_ollama import extract_tour_ollama
from app.services.geocoding import geocode_address
from app.services.opening_hours import fetch_opening_hours
from app.services.optimiser import current_plan, optimise_tour
from app.services.push import notify_user
from app.services.store_catalog import enrich_stop_from_store, match_store
from app.services.store_resolution import (
    claim_matches_store,
    create_store_from_claim,
    order_no_index,
    resolve_stop,
    store_coords,
)

router = APIRouter(prefix="/tours", tags=["tours"])

# Planning surface (extract/commit/optimise/assign/plan edits).
_PLANNERS = Depends(require_role(Role.dispatcher, Role.admin))
# Office reads (drafts, analytics); workers get tour reads via ensure_tour_visible.
_READERS = Depends(require_role(Role.manager, Role.dispatcher, Role.admin))

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
    # The draft edits the plan's *claim* — what the paper says, before the
    # catalog resolves it. Wire names stay street/postal_code/... for the
    # editor UI; they read and write the claimed_* columns.
    return DraftStop(
        id=stop.id,
        customer=stop.customer,
        street=stop.claimed_street,
        postal_code=stop.claimed_postal_code,
        city=stop.claimed_city,
        order_no=stop.claimed_order_no,
        tasks=", ".join(labels) if labels else None,
        remarks=stop.remarks_raw,
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


@router.get("", response_model=list[TourRead], dependencies=[_READERS])
def list_tours(
    db: Annotated[Session, Depends(get_db)],
    status: TourStatus | None = None,
    assigned_user_id: int | None = None,
) -> list[Tour]:
    """All tours, newest week first, optionally filtered (the office list)."""
    query = select(Tour).order_by(Tour.date_from.desc(), Tour.id.desc())
    if status is not None:
        query = query.where(Tour.status == status)
    if assigned_user_id is not None:
        query = query.where(Tour.assigned_user_id == assigned_user_id)
    return list(db.scalars(query))


@router.post("", response_model=TourRead, status_code=201, dependencies=[_PLANNERS])
def create_tour(
    payload: TourCreate,
    db: Annotated[Session, Depends(get_db)],
) -> Tour:
    """Create an empty draft tour (the dispatcher's New-tour flow); stops are
    then added via photo extraction or POST /tours/{id}/stops."""
    if payload.date_to < payload.date_from:
        raise HTTPException(status_code=422, detail="date_to is before date_from")
    tour = Tour(
        customer=payload.customer.strip() or "Unknown",
        calendar_week=payload.calendar_week,
        date_from=payload.date_from,
        date_to=payload.date_to,
        status=TourStatus.draft,
    )
    db.add(tour)
    db.commit()
    db.refresh(tour)
    return tour


@router.post("/extract", response_model=TourDraft, dependencies=[_PLANNERS])
def extract(
    db: Annotated[Session, Depends(get_db)],
    image: Annotated[UploadFile, File()],
    tour_id: Annotated[int | None, Form()] = None,
) -> TourDraft:
    """Extract a draft tour from a photographed plan (vision) and geocode it.

    Runs Claude vision extraction, persists a draft tour + stops (status
    ``draft``/``unconfirmed``) preserving row order, geocodes each stop
    best-effort (cached Nominatim), and returns the draft for the Confirm
    screen. Runs in a threadpool (sync def), so the multi-second model call
    doesn't block the event loop.

    With ``tour_id`` the rows are appended to that existing draft tour instead
    (the office New-tour flow creates the tour first, then uploads the photo);
    the photo's header fields only fill blanks on the existing tour.
    """
    existing_tour: Tour | None = None
    if tour_id is not None:
        existing_tour = db.get(Tour, tour_id)
        if existing_tour is None:
            raise HTTPException(status_code=404, detail="tour not found")
        if existing_tour.status != TourStatus.draft:
            raise HTTPException(
                status_code=409, detail="stops can only be extracted into a draft tour"
            )

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

    if existing_tour is not None:
        tour = existing_tour
        tour.team_lead = tour.team_lead or parsed.team_lead
        tour.employee = tour.employee or parsed.employee
        tour.vehicle = tour.vehicle or parsed.vehicle
        # NB: `or -1` would misread a max of 0 (falsy) as "no rows".
        max_row = db.scalar(
            select(func.max(Stop.row_index)).where(Stop.tour_id == tour.id)
        )
        row_offset = 0 if max_row is None else max_row + 1
    else:
        tour = Tour(
            customer=(parsed.customer or "Unknown").strip() or "Unknown",
            calendar_week=parsed.calendar_week or 0,
            date_from=_parse_iso_date(parsed.date_from) or date.today(),
            date_to=_parse_iso_date(parsed.date_to) or date.today(),
            team_lead=parsed.team_lead,
            employee=parsed.employee,
            vehicle=parsed.vehicle,
            status=TourStatus.draft,
        )
        db.add(tour)
        db.flush()
        row_offset = 0

    for index, extracted in enumerate(parsed.stops):
        status_hint = extracted.status_hint or "unknown"
        stop = Stop(
            tour_id=tour.id,
            row_index=row_offset + index,
            date=_parse_iso_date(extracted.date),
            weekday=extracted.weekday,
            customer=extracted.customer,
            claimed_order_no=extracted.order_no,
            claimed_street=extracted.street,
            claimed_postal_code=extracted.postal_code,
            claimed_city=extracted.city,
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

        # Known store? Link it (address/coordinate/hours then read through the
        # store) and inherit default tasks/minutes; no geocoding needed.
        # Otherwise geocode the claim so the Confirm map has a marker — the
        # result is only the claim's diagnostic coordinate.
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
                stop.claimed_geom = WKTElement(f"POINT({lon} {lat})", srid=4326)
        db.add(stop)

    db.commit()
    return _build_draft(db, tour.id)


@router.get("/{tour_id}", response_model=TourRead)
def get_tour(
    tour_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> Tour:
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")
    ensure_tour_visible(user, tour)
    return tour


@router.patch("/{tour_id}", response_model=TourRead, dependencies=[_PLANNERS])
def update_tour(
    tour_id: int,
    update: TourUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> Tour:
    """Change per-tour settings (currently date_mode). Switching date_mode
    does not reschedule by itself — the client re-runs optimise after."""
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")

    if update.date_mode is not None:
        tour.date_mode = update.date_mode
    db.commit()
    db.refresh(tour)
    return tour


@router.get("/{tour_id}/draft", response_model=TourDraft, dependencies=[_READERS])
def get_draft(
    tour_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> TourDraft:
    """The current draft (pre-commit) tour, for a reloaded/deep-linked Confirm."""
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")
    return _build_draft(db, tour_id)


@router.patch(
    "/{tour_id}/draft/stops/{stop_id}",
    response_model=DraftStop,
    dependencies=[_PLANNERS],
)
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

    # Draft wire fields edit the plan's claim (claimed_* columns).
    claim_fields = {
        "street": "claimed_street",
        "postal_code": "claimed_postal_code",
        "city": "claimed_city",
        "order_no": "claimed_order_no",
    }
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
            setattr(stop, claim_fields.get(field, field), value)
            if field in ("street", "postal_code", "city"):
                address_changed = True
        confidence.pop(field, None)

    stop.confidence = confidence or None

    if address_changed:
        coords = geocode_address(
            db, stop.claimed_street, stop.claimed_postal_code, stop.claimed_city
        )
        stop.claimed_geom = (
            WKTElement(f"POINT({coords[0]} {coords[1]})", srid=4326)
            if coords is not None
            else None
        )
        # The claim changed, so its agreement with the store is unknown again
        # until the next commit re-checks it.
        stop.address_matches_store = None

    db.commit()
    db.refresh(stop, attribute_names=["tasks"])
    return _draft_stop(stop)


@router.post(
    "/{tour_id}/stops",
    response_model=DraftStop,
    status_code=201,
    dependencies=[_PLANNERS],
)
def add_stop(
    tour_id: int,
    payload: DraftStopCreate,
    db: Annotated[Session, Depends(get_db)],
) -> DraftStop:
    """Add a stop by hand to a draft tour (the start-blank path). The stop is
    catalog-matched and geocoded exactly like an extracted row."""
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")
    if tour.status != TourStatus.draft:
        raise HTTPException(
            status_code=409, detail="stops can only be added to a draft tour"
        )

    # NB: `or -1` would misread a max of 0 (falsy) as "no rows".
    max_row = db.scalar(select(func.max(Stop.row_index)).where(Stop.tour_id == tour_id))
    next_row = 0 if max_row is None else max_row + 1
    stop = Stop(
        tour_id=tour_id,
        row_index=next_row,
        customer=payload.customer,
        claimed_order_no=payload.order_no,
        claimed_street=payload.street,
        claimed_postal_code=payload.postal_code,
        claimed_city=payload.city,
        service_minutes=payload.service_minutes,
        status="unconfirmed",
        status_hint="pending",
    )
    for label in (payload.tasks or "").split(","):
        label = label.strip()
        if label:
            stop.tasks.append(Task(task_type=label, raw_label=label))

    store = match_store(db, payload.customer, payload.city, payload.postal_code)
    if store is not None:
        enrich_stop_from_store(stop, store)
    else:
        coords = geocode_address(db, payload.street, payload.postal_code, payload.city)
        if coords is not None:
            lon, lat = coords
            stop.claimed_geom = WKTElement(f"POINT({lon} {lat})", srid=4326)

    db.add(stop)
    db.commit()
    db.refresh(stop, attribute_names=["tasks"])
    return _draft_stop(stop)


@router.get("/{tour_id}/stops", response_model=list[StopDetail])
def list_stops(
    tour_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> list[StopDetail]:
    """Committed stops with address, task labels, and geocoded coordinate.

    Returns every stop of the tour (including ungeocoded/unassigned ones, whose
    lat/lng are null) in the tour plan's original row order. Powers the mobile
    Review (edit hours) and Map (markers + detail) screens.
    """
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")
    ensure_tour_visible(user, tour)

    stops = db.scalars(
        select(Stop)
        .where(Stop.tour_id == tour_id)
        .options(selectinload(Stop.tasks), selectinload(Stop.store))
        .order_by(Stop.row_index)
    ).all()

    # One query for every coordinate — the linked store's geometry, and
    # nothing else. The claim's geocode is diagnostic: markers and the
    # navigate deep-link must never send anyone to a printed typo. Stops
    # without a geocoded store have null lat/lng.
    coords = {
        sid: (lon, lat)
        for sid, lon, lat in db.execute(
            select(Stop.id, func.ST_X(Store.geom), func.ST_Y(Store.geom))
            .select_from(Stop)
            .join(Store, Stop.store_id == Store.id)
            .where(Stop.tour_id == tour_id, Store.geom.isnot(None))
        ).all()
    }

    # One grouped query for the "N past notes" indicators.
    store_ids = {s.store_id for s in stops if s.store_id is not None}
    feedback_counts: dict[int, int] = {}
    if store_ids:
        feedback_counts = dict(
            db.execute(
                select(VisitFeedback.store_id, func.count())
                .where(VisitFeedback.store_id.in_(store_ids))
                .group_by(VisitFeedback.store_id)
            ).all()
        )

    result: list[StopDetail] = []
    for stop in stops:
        lon, lat = coords.get(stop.id, (None, None))
        labels = [task.raw_label or task.task_type for task in stop.tasks]
        result.append(
            StopDetail(
                id=stop.id,
                tour_id=stop.tour_id,
                customer=stop.customer,
                opening_time=stop.effective_opening_time,
                closing_time=stop.effective_closing_time,
                service_minutes=stop.service_minutes,
                hours_source=stop.effective_hours_source,
                status=stop.status,
                completed_at=stop.completed_at,
                assigned_day=stop.assigned_day,
                sequence=stop.sequence,
                eta=stop.eta,
                unassigned_reason=stop.unassigned_reason,
                street=stop.effective_street,
                postal_code=stop.effective_postal_code,
                city=stop.effective_city,
                claimed_street=stop.claimed_street,
                claimed_postal_code=stop.claimed_postal_code,
                claimed_city=stop.claimed_city,
                address_matches_store=stop.address_matches_store,
                address_review_resolved_at=stop.address_review_resolved_at,
                address_review_resolved_by=stop.address_review_resolved_by,
                store_address_provenance=(
                    stop.store.address_provenance if stop.store else None
                ),
                tasks=", ".join(labels) if labels else None,
                remarks=stop.remarks_raw,
                lat=lat,
                lng=lon,
                store_id=stop.store_id,
                store_attributes_complete=(
                    stop.store.attributes_complete if stop.store else None
                ),
                store_feedback_count=(
                    feedback_counts.get(stop.store_id, 0)
                    if stop.store_id is not None
                    else 0
                ),
            )
        )
    return result


@router.post("/{tour_id}/commit", response_model=CommitResult, dependencies=[_PLANNERS])
def commit_tour(
    tour_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> CommitResult:
    """Confirm a tour: resolve every row against the store catalog first.

    Each unlinked row runs the conservative match cascade (order_no →
    normalized-address fuzzy → 50 m proximity; see services.store_resolution).
    A matched row links its store and inherits the verified address, geometry,
    and hours through the effective_* read-through — no geocoding, and the
    store is never overwritten from the plan's text (the plan is the less
    reliable source). An ambiguous match is returned for dispatcher review,
    never auto-linked. A row matching nothing becomes a candidate new store
    (address_provenance='geocoded') and is reported, not silently inserted.
    The only geocoding commit ever does is for those unmatched claims.

    Every linked stop gets address_matches_store: whether the plan's claim
    agrees with the store's verified address. Disagreements keep both values
    and are flagged — the claim is the audit trail of what the paper said.

    Store hours still unknown after linking are looked up from OSM
    (best-effort); manual and previously-fetched hours are never overwritten.
    Suspected duplicate rows are reported for the review UI to resolve —
    commit never deletes data on its own.
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

    stores = list(db.scalars(select(Store)))
    store_by_id = {s.id: s for s in stores}
    by_order_no = order_no_index(db)
    coords = store_coords(db, stores)

    # Extract-time geocodes of the claims, one query (diagnostic coordinates).
    claim_coords = {
        sid: (lon, lat)
        for sid, lon, lat in db.execute(
            select(
                Stop.id, func.ST_X(Stop.claimed_geom), func.ST_Y(Stop.claimed_geom)
            ).where(Stop.tour_id == tour_id, Stop.claimed_geom.isnot(None))
        ).all()
    }

    new_stores: list[NewStoreRead] = []
    review_items: list[MatchReviewItem] = []
    created_store_ids: set[int] = set()

    for stop in stops:
        # Committing the tour confirms its stops (extract leaves them
        # 'unconfirmed'); a stop already marked 'done' keeps its status.
        if stop.status != "done":
            stop.status = "confirmed"

        if stop.store_id is not None:
            continue  # already resolved (extraction match or type-ahead pick)

        claim_coord = claim_coords.get(stop.id)
        resolution = resolve_stop(
            stop,
            stores,
            by_order_no=by_order_no,
            coords=coords,
            claim_coord=claim_coord,
        )

        if resolution.outcome == "unresolved" and claim_coord is None:
            # The one geocode commit permits: an unmatched claim, needed both
            # for the proximity rule and for the candidate store's geometry.
            geocoded = geocode_address(
                db, stop.claimed_street, stop.claimed_postal_code, stop.claimed_city
            )
            if geocoded is not None:
                claim_coord = geocoded
                stop.claimed_geom = WKTElement(
                    f"POINT({claim_coord[0]} {claim_coord[1]})", srid=4326
                )
                resolution = resolve_stop(
                    stop,
                    stores,
                    by_order_no=by_order_no,
                    coords=coords,
                    claim_coord=claim_coord,
                )

        if resolution.outcome == "linked":
            stop.store_id = resolution.store.id
        elif resolution.outcome == "ambiguous":
            review_items.append(
                MatchReviewItem(
                    stop_id=stop.id,
                    customer=stop.customer,
                    reason=resolution.reason or "ambiguous match",
                    candidates=[
                        MatchCandidateRead(
                            store_id=c.store.id,
                            name=c.store.name,
                            score=round(c.score, 1),
                            rule=c.rule,
                        )
                        for c in resolution.candidates
                    ],
                )
            )
        elif stop.customer or stop.claimed_street:
            store = create_store_from_claim(stop, claim_coord)
            db.add(store)
            db.flush()  # assign the id; visible to later rows of this commit
            stores.append(store)
            store_by_id[store.id] = store
            created_store_ids.add(store.id)
            if claim_coord is not None:
                coords[store.id] = claim_coord
            stop.store_id = store.id
            new_stores.append(
                NewStoreRead(stop_id=stop.id, store_id=store.id, name=store.name)
            )

    # Claim-vs-store audit for every linked stop: both values are kept; a
    # mismatch is how the office learns their printed plan was wrong.
    mismatches: list[AddressMismatchRead] = []
    matched = 0
    for stop in stops:
        if stop.store_id is None or stop.store_id not in store_by_id:
            stop.address_matches_store = None
            continue
        store = store_by_id[stop.store_id]
        if stop.store_id not in created_store_ids:
            matched += 1
        stop.address_matches_store = claim_matches_store(stop, store)
        if stop.address_matches_store is False:
            mismatches.append(
                AddressMismatchRead(
                    stop_id=stop.id,
                    store_id=store.id,
                    claimed=", ".join(
                        p
                        for p in (
                            stop.claimed_street,
                            stop.claimed_postal_code,
                            stop.claimed_city,
                        )
                        if p
                    ),
                    verified=", ".join(
                        p for p in (store.street, store.postal_code, store.city) if p
                    ),
                )
            )

    # Hours enrichment happens on the *store* (hours are a property of the
    # shop). Only stores whose hours were never captured are looked up.
    enriched = 0
    for store_id in {s.store_id for s in stops if s.store_id is not None}:
        store = store_by_id.get(store_id)
        if (
            store is None
            or store.hours_source is not None
            or store.opening_time is not None
            or store.closing_time is not None
            or store_id not in coords
        ):
            continue
        lon, lat = coords[store_id]
        try:
            window = fetch_opening_hours(lon, lat)
        except Exception:
            # Best-effort: never fail commit on an Overpass hiccup.
            window = None
        if window is not None:
            store.opening_time, store.closing_time = window
            store.hours_source = HoursSource.osm
            enriched += 1

    # Committing confirms the plan; re-commits on a live tour keep its stage.
    if tour.status == TourStatus.draft:
        tour.status = TourStatus.planned
    db.commit()

    return CommitResult(
        tour_id=tour_id,
        status=tour.status,
        stops_total=len(stops),
        stops_enriched=enriched,
        stops_matched=matched,
        new_stores=new_stores,
        review_items=review_items,
        address_mismatches=mismatches,
        duplicates=_duplicate_groups(stops),
    )


def _duplicate_groups(stops: list[Stop]) -> list[list[int]]:
    """Stop-id groups that look like the same market listed twice."""
    groups: dict[tuple, list[int]] = {}
    for stop in stops:
        if stop.store_id is not None:
            key = ("store", stop.store_id)
        else:
            street = "".join(
                ch for ch in (stop.claimed_street or "").lower() if ch.isalnum()
            )
            if not street:
                continue
            key = ("addr", street, (stop.claimed_postal_code or "").strip())
        groups.setdefault(key, []).append(stop.id)
    return [ids for ids in groups.values() if len(ids) > 1]


@router.post(
    "/{tour_id}/optimise", response_model=OptimiseResult, dependencies=[_PLANNERS]
)
def optimise(
    tour_id: int,
    db: Annotated[Session, Depends(get_db)],
    payload: OptimiseRequest | None = None,
) -> OptimiseResult:
    """Assign every open market to a working day and order it.

    scope='remaining' re-plans mid-week: days before from_date (default
    today) and every completed stop stay untouched; the still-open stops —
    including any stranded on earlier days — spread over the remaining days,
    starting from the last completed stop.
    """
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")

    from_date = None
    if payload is not None and payload.scope == "remaining":
        from_date = payload.from_date or date.today()
    result = optimise_tour(db, tour, from_date=from_date)

    # A freshly optimised draft is planned; a mid-week replan keeps its stage.
    if tour.status == TourStatus.draft:
        tour.status = TourStatus.planned
        db.commit()
    return result


@router.get("/{tour_id}/plan", response_model=OptimiseResult)
def get_plan(
    tour_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> OptimiseResult:
    """The stored schedule, without re-solving — what the map should load.

    Re-optimising on read would overwrite manual edits and mid-week state,
    so this endpoint only mirrors the database. Drive time and day-end are
    solver outputs and read as zero/empty here.
    """
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")
    ensure_tour_visible(user, tour)
    return current_plan(db, tour)


@router.post("/{tour_id}/assign", response_model=TourRead, dependencies=[_PLANNERS])
def assign_tour(
    tour_id: int,
    payload: TourAssignRequest,
    db: Annotated[Session, Depends(get_db)],
    background_tasks: BackgroundTasks,
) -> Tour:
    """Hand the tour to a worker: sets assigned_user_id and status 'assigned'.

    Reassigning an in_progress tour keeps its stage; draft and done tours
    cannot be assigned (commit the plan first / the week is over).
    The (new and displaced) workers are push-notified after the response.
    """
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")
    if tour.status in (TourStatus.draft, TourStatus.done):
        raise HTTPException(
            status_code=409, detail=f"cannot assign a {tour.status.value} tour"
        )

    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="user is deactivated")

    previous_user_id = tour.assigned_user_id
    tour.assigned_user_id = user.id
    if tour.status != TourStatus.in_progress:
        tour.status = TourStatus.assigned
    db.commit()
    db.refresh(tour)

    if user.id != previous_user_id:
        background_tasks.add_task(
            notify_user,
            user.id,
            "New tour assigned",
            f"{tour.customer} — KW {tour.calendar_week}, "
            f"{tour.date_from:%d.%m.} – {tour.date_to:%d.%m.}",
            {"tour_id": tour.id},
        )
        if previous_user_id is not None:
            background_tasks.add_task(
                notify_user,
                previous_user_id,
                "Tour reassigned",
                f"{tour.customer} — KW {tour.calendar_week} was handed to "
                f"{user.name}.",
                {"tour_id": tour.id},
            )
    return tour


@router.post("/{tour_id}/unassign", response_model=TourRead, dependencies=[_PLANNERS])
def unassign_tour(
    tour_id: int,
    db: Annotated[Session, Depends(get_db)],
    background_tasks: BackgroundTasks,
) -> Tour:
    """Take the tour back: clears the assignee; an untouched 'assigned' tour
    returns to 'planned' (progress stages are kept). The displaced worker is
    push-notified after the response."""
    tour = db.get(Tour, tour_id)
    if tour is None:
        raise HTTPException(status_code=404, detail="tour not found")

    previous_user_id = tour.assigned_user_id
    tour.assigned_user_id = None
    if tour.status == TourStatus.assigned:
        tour.status = TourStatus.planned
    db.commit()
    db.refresh(tour)

    if previous_user_id is not None:
        background_tasks.add_task(
            notify_user,
            previous_user_id,
            "Tour unassigned",
            f"{tour.customer} — KW {tour.calendar_week} was taken off your list.",
            {"tour_id": tour.id},
        )
    return tour
