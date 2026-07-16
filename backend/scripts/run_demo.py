"""Live-demo driver for tour 118: simulate the employee's week, compressed.

Flow it supports (run from backend/ with the venv python):

    python -m scripts.run_demo            # wait for dispatch, then play the week
    python -m scripts.run_demo --reset    # put tour 118 back to planned/unassigned

The script signs in as the demo worker and WAITS until a dispatcher assigns
tour 118 in the dashboard — that's the presenter's cue. It then completes the
stops day by day through the real API (so tour status transitions exactly as
in the field), pacing each day over --day-seconds. After each completion the
timestamp is re-stamped in the DB to the stop's planned ETA plus a little
jitter, so the manager's on-time KPI and proof-of-work deltas look like a
real week instead of "everything done within five minutes".

One feedback note (with the demo worker's name) is left at the first store
of day 3 — enough to show the feedback trail without spamming every stop.
"""

import argparse
import random
import sys
import time
from datetime import timedelta

import httpx

from app.db import SessionLocal
from app.models.stop import Stop
from app.models.tour import Tour, TourStatus
from app.models.visit_feedback import VisitFeedback

TOUR_ID = 118
API = "http://localhost:8000"
WORKER = {"email": "demo-worker@e2e.elservice.de", "password": "demo-worker-pass-1"}
FEEDBACK_UUID = "demo118-feedback-1"


def reset() -> None:
    db = SessionLocal()
    tour = db.get(Tour, TOUR_ID)
    stops = db.query(Stop).filter(Stop.tour_id == TOUR_ID).all()
    for stop in stops:
        stop.completed_at = None
    tour.status = TourStatus.planned
    tour.assigned_user_id = None
    deleted = (
        db.query(VisitFeedback)
        .filter(VisitFeedback.client_uuid.like("demo118-%"))
        .delete(synchronize_session=False)
    )
    db.commit()
    db.close()
    print(f"tour {TOUR_ID} reset: planned, unassigned, 0/{len(stops)} completed, "
          f"{deleted} demo feedback row(s) removed")


def backdate(stop_id: int, minutes_jitter: int) -> str:
    """Re-stamp completed_at to the stop's plan ETA + jitter (demo realism)."""
    db = SessionLocal()
    stop = db.get(Stop, stop_id)
    if stop.eta is not None:
        stop.completed_at = stop.eta + timedelta(minutes=minutes_jitter)
    stamped = stop.completed_at.strftime("%a %H:%M")
    db.commit()
    db.close()
    return stamped


def backdate_feedback(client_uuid: str, stop_id: int) -> None:
    db = SessionLocal()
    stop = db.get(Stop, stop_id)
    row = (
        db.query(VisitFeedback)
        .filter(VisitFeedback.client_uuid == client_uuid)
        .one_or_none()
    )
    if row is not None and stop.completed_at is not None:
        row.created_at = stop.completed_at + timedelta(minutes=2)
    db.commit()
    db.close()


def _sign_in(client: httpx.Client) -> None:
    token = client.post("/auth/login", json=WORKER).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"


def _request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """Request that survives a demo rig hiccup: transient network errors are
    retried with backoff, an expired token (401 after a long wait at the
    'assign it now' prompt) triggers a re-login."""
    for attempt in range(10):  # ~5 min budget: rides out a docker-rig recovery
        try:
            resp = client.request(method, url, **kwargs)
        except httpx.HTTPError:
            time.sleep(5 * (attempt + 1))
            continue
        if resp.status_code == 401:
            _sign_in(client)
            continue
        if resp.status_code >= 500:  # rig mid-recovery answers 5xx for a bit
            time.sleep(5 * (attempt + 1))
            continue
        return resp
    raise RuntimeError(f"{method} {url} kept failing — is the backend up?")


def run(day_seconds: float) -> None:
    client = httpx.Client(base_url=API, timeout=30)
    _sign_in(client)

    print(f"Signed in as Demo Mitarbeiter. Waiting for the dispatcher to assign "
          f"tour {TOUR_ID} …  (assign it in the dashboard now)")
    while True:
        mine = _request(client, "GET", "/me/tours").json()
        if any(t["id"] == TOUR_ID for t in mine):
            break
        time.sleep(3)
    print(f"Tour {TOUR_ID} assigned — the week begins.\n")

    stops = _request(client, "GET", f"/tours/{TOUR_ID}/stops").json()
    days: dict[str, list[dict]] = {}
    for s in stops:
        days.setdefault(s["assigned_day"] or "unscheduled", []).append(s)
    for day_stops in days.values():
        day_stops.sort(key=lambda s: s["sequence"] or 0)

    rng = random.Random(118)
    feedback_done = False
    for day_no, day in enumerate(sorted(days), start=1):
        day_stops = days[day]
        pause = day_seconds / max(len(day_stops), 1)
        print(f"— Tag {day_no} ({day}) · {len(day_stops)} Stopps —")
        for s in day_stops:
            time.sleep(pause)
            _request(client, "POST", f"/stops/{s['id']}/complete", json={})
            # ~80% within the 30-minute on-time tolerance.
            jitter = rng.choice([-8, -3, 2, 6, 11, 17, 24, 28, 41, 55])
            stamped = backdate(s["id"], jitter)
            where = ", ".join(x for x in (s["street"], s["city"]) if x) or (
                s["customer"] or f"Stopp {s['id']}"
            )
            print(f"   ✓ {where:48s}  erledigt {stamped} ({jitter:+d} min zur ETA)")

            if day_no == 3 and not feedback_done and s["store_id"] is not None:
                _request(client, "POST", "/feedback", json={
                    "stop_id": s["id"],
                    "client_uuid": FEEDBACK_UUID,
                    "tags": ["parking_full"],
                    "note": "Parkplatz war komplett voll — Anlieferung über den "
                            "Seiteneingang, ca. 15 min verloren.",
                })
                backdate_feedback(FEEDBACK_UUID, s["id"])
                feedback_done = True
                print("   💬 Feedback hinterlassen (Parkplatz voll)")
    print("\nWoche abgeschlossen — Tour steht auf 'done'.")
    print("Jetzt: als Manager einloggen → Overview, Proof of work, Store-360.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true",
                        help="reset tour 118 to planned/unassigned and exit")
    parser.add_argument("--day-seconds", type=float, default=75,
                        help="how long each demo day takes (default 75s)")
    args = parser.parse_args()
    if args.reset:
        reset()
        sys.exit(0)
    run(args.day_seconds)
