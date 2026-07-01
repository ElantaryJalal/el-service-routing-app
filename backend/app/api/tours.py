from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.stop import HoursSource, Stop
from app.models.tour import Tour
from app.schemas.optimise import OptimiseResult
from app.schemas.stop import CommitResult
from app.services.opening_hours import fetch_opening_hours
from app.services.optimiser import optimise_tour

router = APIRouter(prefix="/tours", tags=["tours"])


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
        if stop.geom is None or stop.hours_source != HoursSource.default:
            continue

        lon, lat = db.execute(
            select(func.ST_X(Stop.geom), func.ST_Y(Stop.geom)).where(
                Stop.id == stop.id
            )
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
