"""GET /stores/suggest: draft-editor type-ahead over catalog + past stops.

Requires a reachable database; skipped otherwise. Uses the conftest admin
override — role behaviour for /stores is covered by the RBAC suite.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.store import Store
from app.models.tour import Tour, TourStatus


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")

client = TestClient(app)


@pytest.fixture
def world():
    """One catalog store and one done tour with an unmatched stop, both with
    names no real data uses."""
    db = SessionLocal()
    store = Store(
        name="Suggesttest Markt Nord",
        aliases=["SGT Nord"],
        street="Suggestweg 1",
        postal_code="04999",
        city="Suggestadt",
        default_tasks=["VSS", "UR"],
        default_service_minutes=90,
    )
    db.add(store)
    tour = Tour(
        customer="Suggesttest",
        calendar_week=9,
        date_from=date(2027, 3, 1),
        date_to=date(2027, 3, 5),
        status=TourStatus.done,
    )
    db.add(tour)
    db.flush()
    stop = Stop(
        tour_id=tour.id,
        row_index=0,
        customer="Suggesttest Getraenkemarkt",
        claimed_street="Historiengasse 9",
        claimed_postal_code="04998",
        claimed_city="Suggestadt",
        status="done",
    )
    db.add(stop)
    db.commit()
    ids = {"store": store.id, "tour": tour.id}
    db.close()

    yield ids

    db = SessionLocal()
    db.query(Stop).filter(Stop.tour_id == ids["tour"]).delete()
    db.query(Tour).filter(Tour.id == ids["tour"]).delete()
    db.query(Store).filter(Store.id == ids["store"]).delete()
    db.commit()
    db.close()


def _suggest(q: str) -> list[dict]:
    resp = client.get("/stores/suggest", params={"q": q})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_catalog_match_carries_row_fill(world):
    hits = _suggest("suggesttest markt")
    assert any(
        s["source"] == "catalog"
        and s["store_id"] == world["store"]
        and s["name"] == "Suggesttest Markt Nord"
        and s["street"] == "Suggestweg 1"
        and s["postal_code"] == "04999"
        and s["service_minutes"] == 90
        and s["tasks"] == "VSS, UR"
        for s in hits
    ), hits


def test_order_number_match_links_store():
    """Typing the Auftrag/VST number surfaces the exact store (via history),
    carrying its store_id so the row links it with no re-typing."""
    db = SessionLocal()
    store = Store(
        name="Ordertest Markt",
        street="Ordersweg 2",
        postal_code="04997",
        city="Orderstadt",
    )
    db.add(store)
    tour = Tour(
        customer="Ordertest",
        calendar_week=10,
        date_from=date(2027, 3, 8),
        date_to=date(2027, 3, 12),
        status=TourStatus.done,
    )
    db.add(tour)
    db.flush()
    stop = Stop(
        tour_id=tour.id,
        row_index=0,
        customer="Ordertest Markt",
        order_no="VST-778812",
        store_id=store.id,
        status="done",
    )
    db.add(stop)
    db.commit()
    ids = {"store": store.id, "tour": tour.id}
    db.close()

    try:
        hits = _suggest("778812")
        assert any(
            s["source"] == "catalog"
            and s["store_id"] == ids["store"]
            and s["order_no"] == "VST-778812"
            for s in hits
        ), hits
    finally:
        db = SessionLocal()
        db.query(Stop).filter(Stop.tour_id == ids["tour"]).delete()
        db.query(Tour).filter(Tour.id == ids["tour"]).delete()
        db.query(Store).filter(Store.id == ids["store"]).delete()
        db.commit()
        db.close()


def test_alias_and_address_match(world):
    assert any(s["name"] == "Suggesttest Markt Nord" for s in _suggest("SGT Nord"))
    assert any(s["name"] == "Suggesttest Markt Nord" for s in _suggest("Suggestweg"))


def test_history_stop_suggested(world):
    hits = _suggest("Getraenkemarkt")
    assert any(
        s["source"] == "history"
        and s["name"] == "Suggesttest Getraenkemarkt"
        and s["street"] == "Historiengasse 9"
        for s in hits
    ), hits


def test_catalog_ranks_before_history(world):
    hits = _suggest("Suggestadt")  # city matches both entries
    sources = [s["source"] for s in hits if s["name"].startswith("Suggesttest")]
    assert sources == sorted(sources)  # catalog < history alphabetically


def test_short_query_rejected(world):
    assert client.get("/stores/suggest", params={"q": "a"}).status_code == 422
