"""Seed a showcase catalog of fully-populated demo stores.

The office store catalog only looks alive once its stores carry the P3+ data a
real crew slowly crowdsources: size, mall/parking flags, opening hours, and
service defaults. This script seeds a handful of Aldi Nord stores with all of
that filled in so the catalog, attribute filters, and per-store views have
something rich to render for a demo — WITHOUT touching the real, verified
catalog a production tour matches against.

Every store here is marked is_demo=True, which keeps it out of plan matching
(name/order-no resolution never attaches it to a real tour) and out of the
office store list unless the "show demo data" toggle is on. Re-running replaces
the showcase set in place; it never deletes a real store.

    cd backend
    DATABASE_URL=postgresql+psycopg://el_service:el_service@localhost:5544/el_service \
      python -m scripts.seed_demo_showcase
"""

from datetime import UTC, datetime, time

from geoalchemy2.elements import WKTElement

from app.db import SessionLocal
from app.models.store import (
    AddressProvenance,
    GeomProvenance,
    HoursSource,
    Store,
    StoreSize,
)

SEEDED_BY = "seed_demo_showcase"

# Fully-populated showcase stores. The spread is deliberate — small/medium/large,
# mall vs. standalone, parking vs. none, one early-closer — so every catalog
# filter ("needs attributes" excluded, size/mall/parking facets) has variety to
# show. lon/lat are real Leipzig-area coordinates; hours are labelled `seeded`
# rather than passed off as OSM-checked.
#
# (name, [aliases], street, plz, city, lon, lat, size, in_mall, has_parking,
#  open, close, service_min, [default_tasks])
STORES = [
    (
        "Aldi Leipzig Zentrum",
        ["Aldi Zentrum", "Aldi Markt Leipzig"],
        "Markt 1",
        "04109",
        "Leipzig",
        12.3731,
        51.3397,
        StoreSize.large,
        True,  # in a downtown mall
        False,  # no dedicated lot
        time(7, 0),
        time(21, 0),
        70,
        ["EKW", "Fussmatten"],
    ),
    (
        "Aldi Gohlis",
        ["Aldi Georg-Schumann"],
        "Georg-Schumann-Str. 100",
        "04155",
        "Leipzig",
        12.3600,
        51.3720,
        StoreSize.medium,
        False,
        True,
        time(7, 0),
        time(20, 0),
        45,
        ["EKW"],
    ),
    (
        "Aldi Connewitz",
        [],
        "Bornaische Str. 50",
        "04277",
        "Leipzig",
        12.3800,
        51.3100,
        StoreSize.large,
        False,
        True,
        time(7, 0),
        time(20, 0),
        80,
        ["Gaskuehler", "EKW"],
    ),
    (
        "Aldi Lindenau",
        ["Aldi Merseburger Str."],
        "Merseburger Str. 40",
        "04177",
        "Leipzig",
        12.3300,
        51.3400,
        StoreSize.small,
        False,
        False,
        time(8, 0),
        time(13, 0),  # early-closer, exercises the feasibility warning
        50,
        ["EKW", "Koerbe Sammelstation"],
    ),
    (
        "Aldi Grünau",
        ["Aldi Stuttgarter Allee"],
        "Stuttgarter Allee 10",
        "04209",
        "Leipzig",
        12.2900,
        51.3150,
        StoreSize.large,
        True,  # in the Allee-Center
        True,
        time(7, 0),
        time(20, 0),
        90,
        ["Gaskuehler"],
    ),
    (
        "Aldi Schkeuditz",
        [],
        "Rathausplatz 2",
        "04435",
        "Schkeuditz",
        12.2200,
        51.3960,
        StoreSize.medium,
        False,
        True,
        time(7, 0),
        time(20, 0),
        55,
        ["EKW"],
    ),
    (
        "Aldi Markkleeberg",
        [],
        "Rathausstr. 5",
        "04416",
        "Markkleeberg",
        12.3700,
        51.2750,
        StoreSize.small,
        False,
        True,
        time(8, 0),
        time(19, 0),
        40,
        ["EKW", "Fussmatten"],
    ),
    (
        "Aldi Günthersdorf",
        ["Aldi Nova Eventis"],
        "Nova-Eventis-Ring 1",
        "06254",
        "Günthersdorf",
        12.1150,
        51.3458,
        StoreSize.large,
        True,  # Nova Eventis mall
        True,
        time(9, 0),
        time(20, 0),
        75,
        ["EKW", "Fussmatten"],
    ),
]


def main() -> None:
    db = SessionLocal()
    try:
        # Replace the previous showcase set in place. Only is_demo stores are
        # touched, so the real, verified catalog is never at risk. Showcase
        # stores are catalog-only (no stops reference them), so a plain delete
        # is safe.
        removed = (
            db.query(Store)
            .filter(Store.is_demo.is_(True))
            .delete(synchronize_session=False)
        )
        db.flush()

        now = datetime.now(UTC)
        for (
            name,
            aliases,
            street,
            plz,
            city,
            lon,
            lat,
            size,
            in_mall,
            has_parking,
            opening,
            closing,
            service_min,
            tasks,
        ) in STORES:
            db.add(
                Store(
                    name=name,
                    aliases=aliases or None,
                    street=street,
                    postal_code=plz,
                    city=city,
                    geom=WKTElement(f"POINT({lon} {lat})", srid=4326),
                    address_provenance=AddressProvenance.verified,
                    geom_provenance=GeomProvenance.verified,
                    opening_time=opening,
                    closing_time=closing,
                    hours_source=HoursSource.seeded,
                    size=size,
                    in_mall=in_mall,
                    has_parking=has_parking,
                    attributes_updated_at=now,
                    attributes_updated_by=SEEDED_BY,
                    default_tasks=tasks,
                    default_service_minutes=service_min,
                    is_demo=True,
                )
            )

        db.commit()
        print(
            f"Seeded {len(STORES)} demo showcase stores "
            f"(removed {removed} prior demo store(s))."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
