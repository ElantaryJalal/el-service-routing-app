"""One-off data cleanup for the paper-plan alignment (migration 0016).

The demo tours carry the exact bugs the alignment fixes, baked in by earlier
extractions:

  * internal codes (Gewerke, VFL, VDP) captured into team_lead/employee;
  * the paper's "Team-Nr." buried inside the free-text employee field instead
    of the new team_no column;
  * one row (tour 118 / Meinerzhagen) whose client was stamped with the tour's
    dominant "ALDI NORD BEUCHA" even though the shop is HIT, and whose imported
    remark ends in a dangling "0:" truncation artifact.

This scrubs the stored rows so the fixes are visible in the running app. It is
idempotent (safe to re-run) and only touches demo data. New imports come out
clean on their own via the updated extraction + resolution.

    cd backend
    DATABASE_URL=... python -m scripts.cleanup_paper_alignment
"""

import re

from app.db import SessionLocal
from app.models.stop import Stop
from app.models.tour import Tour
from app.services.extraction_local import _TEAM_NO, _clean_header_value

# The Meinerzhagen row's real client, per the paper plan (HIT, not ALDI).
MEINERZHAGEN_CLIENT = "HIT Frische 111"
# A trailing short "<digits>:" left by a truncated remark cell (e.g. " 0:").
_DANGLING_TAIL = re.compile(r"\s*\d{1,2}:\s*$")


def _lift_team_no(tour: Tour) -> None:
    """Pull a "Team-Nr." value out of team_lead/employee into team_no, and
    strip the label + any internal codes from the free-text name fields."""
    for source in (tour.employee, tour.team_lead):
        if not tour.team_no and source:
            match = _TEAM_NO.search(source)
            if match:
                tour.team_no = match.group(1).strip()
    tour.team_lead = _clean_header_value(tour.team_lead)
    tour.employee = _clean_header_value(tour.employee)


def main() -> None:
    db = SessionLocal()
    try:
        tours = db.query(Tour).all()
        for tour in tours:
            _lift_team_no(tour)

        # Fix the Meinerzhagen row: its store is HIT, so its client is HIT —
        # the "ALDI NORD BEUCHA" stamp erased a real distinction.
        meinerzhagen = (
            db.query(Stop)
            .filter(
                Stop.claimed_city.ilike("%meinerzhagen%"),
                Stop.customer.ilike("%aldi%"),
            )
            .all()
        )
        for stop in meinerzhagen:
            stop.customer = MEINERZHAGEN_CLIENT
            if stop.remarks_raw:
                stop.remarks_raw = _DANGLING_TAIL.sub("", stop.remarks_raw).rstrip()

        db.commit()

        print(f"Cleaned {len(tours)} tour header(s); team_no lifted where present.")
        for tour in tours:
            print(
                f"  tour {tour.id}: team_lead={tour.team_lead!r} "
                f"employee={tour.employee!r} team_no={tour.team_no!r} "
                f"vehicle={tour.vehicle!r}"
            )
        print(
            f"Fixed {len(meinerzhagen)} Meinerzhagen row(s) -> {MEINERZHAGEN_CLIENT!r}."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
