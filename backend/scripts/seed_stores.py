"""Seed the store catalog (the known supermarkets EL Service services).

Populates `stores` with canonical name/address/coordinate/default tasks so that
extract can resolve a photographed store name to its record and skip geocoding.
Idempotent: clears the catalog and reinserts. Prints the row count.

    cd backend
    DATABASE_URL=postgresql+psycopg://el_service:el_service@localhost:5544/el_service \
      python -m scripts.seed_stores
"""

from geoalchemy2.elements import WKTElement

from app.db import SessionLocal
from app.models.store import Store

# (name, street, plz, city, lon, lat, default_service_min, [default_tasks])
STORES = [
    (
        "Aldi Zentrum",
        "Markt 1",
        "04109",
        "Leipzig",
        12.3731,
        51.3397,
        60,
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
        ["EKW", "Koerbe Sammelstation"],
    ),
    (
        "Aldi Reudnitz",
        "Dresdner Str. 80",
        "04317",
        "Leipzig",
        12.4100,
        51.3350,
        50,
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
        ["EKW", "Fussmatten"],
    ),
    (
        "Aldi Merseburg",
        "Merseburger Str. 5",
        "06217",
        "Merseburg",
        11.9910,
        51.3540,
        60,
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
        ["EKW", "Fussmatten"],
    ),
    (
        "Aldi Halle",
        "Leipziger Str. 12",
        "06108",
        "Halle",
        11.9700,
        51.4820,
        55,
        ["EKW", "Gaskuehler"],
    ),
]


def main() -> None:
    db = SessionLocal()
    try:
        db.query(Store).delete()
        for name, street, plz, city, lon, lat, svc, tasks in STORES:
            db.add(
                Store(
                    name=name,
                    street=street,
                    postal_code=plz,
                    city=city,
                    geom=WKTElement(f"POINT({lon} {lat})", srid=4326),
                    default_tasks=tasks,
                    default_service_minutes=svc,
                )
            )
        db.commit()
        print(f"Seeded {len(STORES)} stores into the catalog.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
