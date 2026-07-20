"""One-off demo cleanup: delete leftover test/draft tours.

Keeps only the real demo content — tour 118 (the KW29 demo week), and the
done history tours 119/1271 that feed the learned service times and the
analytics trend. Everything else in the tours table is abandoned test data
(Unknown drafts, duplicate extraction runs, empty shells); none of it has
service-ledger or feedback rows (verified before writing this script), so
deleting the tours (stops/tasks cascade) is side-effect free.

Usage: python -m scripts.cleanup_demo_tours [--dry-run]
"""

import sys

from sqlalchemy import text

from app.db import SessionLocal

KEEP = {118, 119, 1271}


def main() -> None:
    dry = "--dry-run" in sys.argv
    db = SessionLocal()
    doomed = [
        (row.id, row.customer, row.status)
        for row in db.execute(
            text("SELECT id, customer, status FROM tours WHERE id != ALL(:keep)"),
            {"keep": list(KEEP)},
        )
    ]
    if not doomed:
        print("nothing to delete")
        return
    for tour_id, customer, status in doomed:
        print(f"delete tour {tour_id} ({customer!r}, {status})")
    # Safety: refuse if any doomed tour still owns ledger or feedback rows.
    ids = [t[0] for t in doomed]
    ledger = db.execute(
        text("SELECT count(*) FROM service_records WHERE tour_id = ANY(:ids)"),
        {"ids": ids},
    ).scalar()
    feedback = db.execute(
        text("SELECT count(*) FROM visit_feedback WHERE tour_id = ANY(:ids)"),
        {"ids": ids},
    ).scalar()
    if ledger or feedback:
        sys.exit(f"refusing: {ledger} ledger / {feedback} feedback rows attached")
    if dry:
        print(f"dry run — would delete {len(ids)} tours")
        return
    stops = db.execute(
        text("DELETE FROM stops WHERE tour_id = ANY(:ids)"), {"ids": ids}
    ).rowcount
    tours = db.execute(
        text("DELETE FROM tours WHERE id = ANY(:ids)"), {"ids": ids}
    ).rowcount
    db.commit()
    print(f"deleted {tours} tours, {stops} stops")


if __name__ == "__main__":
    main()
