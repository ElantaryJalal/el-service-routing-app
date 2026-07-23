"""Demo/real separation and store-name resolution on office queries.

Requires a reachable database with migrations applied; skipped otherwise.
"""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.store import Store
from app.models.tour import Tour, TourStatus
from app.models.visit_feedback import VisitFeedback
from app.services.store_catalog import match_store


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")

client = TestClient(app)

# A week far from any real/dev data so the aggregates are deterministic.
WEEK_FROM, WEEK_TO = date(2027, 5, 3), date(2027, 5, 9)
STAMP = datetime(2027, 5, 3, 9, 0, tzinfo=UTC)


@pytest.fixture
def world():
    """A real and a demo tour in the same week; real, demo, and duplicated
    feedback rows against a named store."""
    db = SessionLocal()
    store = Store(name="DemoSep-Test Markt", city="Teststadt", postal_code="99401")
    real = Tour(
        customer="DemoSep Real",
        calendar_week=18,
        date_from=WEEK_FROM,
        date_to=date(2027, 5, 7),
        status=TourStatus.planned,
    )
    demo = Tour(
        customer="DemoSep Demo",
        calendar_week=18,
        date_from=WEEK_FROM,
        date_to=date(2027, 5, 7),
        status=TourStatus.planned,
        is_demo=True,
    )
    db.add_all([store, real, demo])
    db.flush()
    # One real and one demo visit to the store (stops cascade with the tours).
    db.add_all(
        [
            Stop(tour_id=real.id, row_index=0, store_id=store.id),
            Stop(tour_id=demo.id, row_index=0, store_id=store.id, is_demo=True),
        ]
    )

    def note(uuid, text, is_demo=False, created=STAMP):
        return VisitFeedback(
            store_id=store.id,
            employee="Demo Mitarbeiter" if is_demo else "Echte Kraft",
            tags=[],
            note=text,
            client_uuid=uuid,
            is_demo=is_demo,
            created_at=created,
        )

    db.add_all(
        [
            note("demosep-real-1", "Alles sauber"),
            # Identical duplicate pair (offline-sync artefact) -> one entry.
            note("demosep-dup-1", "Kühlregal defekt"),
            note("demosep-dup-2", "Kühlregal defekt"),
            note("demosep-demo-1", "Parkplatz eng (Demo)", is_demo=True),
        ]
    )
    db.commit()
    ids = (store.id, real.id, demo.id)
    db.close()

    yield ids

    db = SessionLocal()
    db.query(VisitFeedback).filter(VisitFeedback.client_uuid.like("demosep-%")).delete(
        synchronize_session=False
    )
    db.query(Tour).filter(Tour.id.in_(ids[1:])).delete(synchronize_session=False)
    db.query(Store).filter(Store.id == ids[0]).delete()
    db.commit()
    db.close()


def test_feedback_excludes_demo_dedupes_and_names_stores(world):
    store_id, _, _ = world

    rows = client.get("/feedback", params={"store_id": store_id}).json()
    notes = [r["note"] for r in rows]
    # Demo row gone, duplicate collapsed to one.
    assert "Parkplatz eng (Demo)" not in notes
    assert notes.count("Kühlregal defekt") == 1
    assert len(rows) == 2
    # Every row names its store — nothing renders a raw id.
    assert all(r["store_name"] == "DemoSep-Test Markt" for r in rows)
    assert all(r["store_city"] == "Teststadt" for r in rows)

    # The toggle brings demo rows back (still deduplicated).
    rows = client.get(
        "/feedback", params={"store_id": store_id, "include_demo": True}
    ).json()
    assert "Parkplatz eng (Demo)" in [r["note"] for r in rows]
    assert len(rows) == 3


def test_store_feedback_excludes_demo_and_dedupes(world):
    store_id, _, _ = world

    rows = client.get(f"/stores/{store_id}/feedback").json()
    notes = [r["note"] for r in rows]
    assert "Parkplatz eng (Demo)" not in notes
    assert notes.count("Kühlregal defekt") == 1
    assert len(rows) == 2

    rows = client.get(
        f"/stores/{store_id}/feedback", params={"include_demo": True}
    ).json()
    assert "Parkplatz eng (Demo)" in [r["note"] for r in rows]
    assert len(rows) == 3


def test_store_visits_exclude_demo_stops(world):
    store_id, real_tour_id, demo_tour_id = world

    rows = client.get(f"/stores/{store_id}/visits").json()
    assert [r["tour_id"] for r in rows] == [real_tour_id]

    rows = client.get(
        f"/stores/{store_id}/visits", params={"include_demo": True}
    ).json()
    assert sorted(r["tour_id"] for r in rows) == sorted([real_tour_id, demo_tour_id])


@pytest.fixture
def demo_store():
    """A single is_demo showcase store with a distinctive name."""
    db = SessionLocal()
    store = Store(
        name="DemoShowcase-Only Markt",
        city="Schaustadt",
        postal_code="99777",
        is_demo=True,
    )
    db.add(store)
    db.commit()
    store_id, store_name = store.id, store.name
    db.close()

    yield store_id, store_name

    db = SessionLocal()
    db.query(Store).filter(Store.id == store_id).delete()
    db.commit()
    db.close()


def test_store_list_hides_demo_stores(demo_store):
    _, name = demo_store

    names = [s["name"] for s in client.get("/stores").json()]
    assert name not in names

    # The toggle brings the showcase store back into the catalog.
    rows = client.get("/stores", params={"include_demo": True}).json()
    assert name in [s["name"] for s in rows]


def test_match_store_skips_demo_stores(demo_store):
    _, name = demo_store

    db = SessionLocal()
    try:
        # An exact-name query must not resolve to the demo store — it would
        # otherwise pin a real plan row to showcase data.
        assert match_store(db, name, postal_code="99777") is None
    finally:
        db.close()


def test_overview_excludes_demo_tours(world):
    params = {"date_from": WEEK_FROM.isoformat(), "date_to": WEEK_TO.isoformat()}

    body = client.get("/reports/overview", params=params).json()
    assert body["tours"]["total"] == 1  # the real tour only

    body = client.get(
        "/reports/overview", params={**params, "include_demo": True}
    ).json()
    assert body["tours"]["total"] == 2
