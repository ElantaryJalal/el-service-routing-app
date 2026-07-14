"""Seed a demo tour of Leipzig-area markets for local testing.

Creates one confirmed tour with several geocoded stops (so commit/optimise/
GET-stops all have something to work with), including one early-closing store and
one stop without a location to exercise the "unassigned" path. Prints the new
tour id.

    cd backend
    DATABASE_URL=postgresql+psycopg://el_service:el_service@localhost:5544/el_service \
      python -m scripts.seed_demo_tour
"""

from datetime import date, time

from geoalchemy2.elements import WKTElement

from app.db import SessionLocal
from app.models.stop import HoursSource, Stop
from app.models.task import Task
from app.models.tour import Tour, TourStatus

DEMO_CUSTOMER = "DEMO Aldi Nord (Leipzig + Saxony-Anhalt)"

# (customer, street, plz, city, lon, lat, service_min, closing, [tasks])
# 04xxx = Saxony (Leipzig area); 06xxx = Saxony-Anhalt, ~25-30 km west across the
# state line — those exercise OSRM coverage, so the routing extract must merge
# Sachsen + Sachsen-Anhalt (+ Thüringen), not Sachsen alone.
STOPS = [
    # --- Saxony (Leipzig) ---
    (
        "Aldi Zentrum",
        "Markt 1",
        "04109",
        "Leipzig",
        12.3731,
        51.3397,
        60,
        time(20, 0),
        ["EKW", "Fussmatten"],
    ),
    (
        "Aldi Gohlis",
        "Georg-Schumann-Str. 100",
        "04155",
        "Leipzig",
        12.3600,
        51.3720,
        45,
        time(20, 0),
        ["EKW"],
    ),
    (
        "Aldi Connewitz",
        "Bornaische Str. 50",
        "04277",
        "Leipzig",
        12.3800,
        51.3100,
        75,
        time(19, 0),
        ["Gaskuehler", "EKW"],
    ),
    (
        "Aldi Lindenau",
        "Merseburger Str. 40",
        "04177",
        "Leipzig",
        12.3300,
        51.3400,
        60,
        time(13, 0),
        ["EKW", "Koerbe Sammelstation"],
    ),  # early close
    (
        "Aldi Reudnitz",
        "Dresdner Str. 80",
        "04317",
        "Leipzig",
        12.4100,
        51.3350,
        50,
        time(20, 0),
        ["EKW"],
    ),
    (
        "Aldi Grunau",
        "Stuttgarter Allee 10",
        "04209",
        "Leipzig",
        12.2900,
        51.3150,
        90,
        time(19, 0),
        ["Gaskuehler"],
    ),
    (
        "Aldi Schkeuditz",
        "Rathausplatz 2",
        "04435",
        "Schkeuditz",
        12.2200,
        51.3960,
        60,
        time(20, 0),
        ["EKW"],
    ),
    (
        "Aldi Markkleeberg",
        "Rathausstr. 5",
        "04416",
        "Markkleeberg",
        12.3700,
        51.2750,
        45,
        time(20, 0),
        ["EKW", "Fussmatten"],
    ),
    # --- Saxony-Anhalt (across the state line, ~25-30 km west) ---
    (
        "Aldi Merseburg",
        "Merseburger Str. 5",
        "06217",
        "Merseburg",
        11.9910,
        51.3540,
        60,
        time(20, 0),
        ["EKW"],
    ),
    (
        "Aldi Leuna",
        "Rudolf-Breitscheid-Str. 2",
        "06237",
        "Leuna",
        12.0130,
        51.3190,
        45,
        time(19, 0),
        ["Gaskuehler", "EKW"],
    ),
    (
        "Aldi Günthersdorf",
        "Nova-Eventis-Ring 1",
        "06254",
        "Günthersdorf",
        12.1150,
        51.3458,
        75,
        time(20, 0),
        ["EKW", "Fussmatten"],
    ),
]


def main() -> None:
    db = SessionLocal()
    try:
        # Clean up prior demo runs (any DEMO_* customer) so re-seeding stays tidy.
        old = db.query(Tour).filter(Tour.customer.like("DEMO %")).all()
        for t in old:
            db.delete(t)  # cascades to stops + tasks
        db.flush()

        tour = Tour(
            customer=DEMO_CUSTOMER,
            calendar_week=28,
            date_from=date(2026, 7, 6),  # Mon
            date_to=date(2026, 7, 10),  # Fri
            employee="Demo Employee",
            status=TourStatus.planned,
        )
        db.add(tour)
        db.flush()

        for i, (cust, street, plz, city, lon, lat, svc, close, tasks) in enumerate(
            STOPS
        ):
            stop = Stop(
                tour_id=tour.id,
                row_index=i,
                customer=cust,
                street=street,
                postal_code=plz,
                city=city,
                service_minutes=svc,
                opening_time=time(7, 0),
                closing_time=close,
                hours_source=HoursSource.osm,
                status="confirmed",
                status_hint="pending",
                geom=WKTElement(f"POINT({lon} {lat})", srid=4326),
            )
            db.add(stop)
            db.flush()
            for label in tasks:
                db.add(Task(stop_id=stop.id, task_type=label.upper(), raw_label=label))

        # One stop with no geom → shows up as "unassigned: missing location".
        db.add(
            Stop(
                tour_id=tour.id,
                row_index=len(STOPS),
                customer="Aldi (address unclear)",
                street="Unleserlich",
                city="Leipzig",
                service_minutes=60,
                status="confirmed",
                status_hint="pending",
            )
        )

        db.commit()
        print(
            f"Seeded tour id={tour.id} with {len(STOPS) + 1} stops "
            f"({DEMO_CUSTOMER}, week {tour.calendar_week})."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
