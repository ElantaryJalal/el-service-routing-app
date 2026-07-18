"""Store-catalog fuzzy matching and stop enrichment.

Requires a reachable database with migrations applied; skipped when the DB is
unreachable. No network or API calls. Uses fictional store names/postal codes so
the test is independent of any seeded catalog.
"""

import pytest
from geoalchemy2.elements import WKTElement

from app.db import SessionLocal, engine
from app.models.stop import Stop
from app.models.store import Store
from app.models.task import Task
from app.services.store_catalog import (
    enrich_stop_from_store,
    match_store,
    match_store_in_text,
)


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")


@pytest.fixture
def catalog():
    """Two fictional catalog stores; yields their ids and cleans up after."""
    db = SessionLocal()
    nord = Store(
        name="Testmarkt Nordstern",
        aliases=["Testmarkt Nord"],
        street="Teststr. 1",
        postal_code="99001",
        city="Teststadt",
        geom=WKTElement("POINT(12.38 51.31)", srid=4326),
        default_tasks=["EKW", "Gaskuehler"],
        default_service_minutes=75,
    )
    sued = Store(
        name="Testmarkt Suedwind",
        street="Testweg 2",
        postal_code="99002",
        city="Andersstadt",
        geom=WKTElement("POINT(11.99 51.35)", srid=4326),
        default_tasks=["EKW"],
        default_service_minutes=60,
    )
    db.add_all([nord, sued])
    db.commit()
    ids = (nord.id, sued.id)
    db.close()

    yield ids

    db = SessionLocal()
    db.query(Store).filter(Store.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    db.close()


def test_match_store(catalog):
    nord_id, sued_id = catalog
    db = SessionLocal()

    # Exact name + locality.
    assert match_store(db, "Testmarkt Nordstern", "Teststadt", "99001").id == nord_id
    # Messy casing/punctuation/whitespace still resolves (normalized similarity).
    assert match_store(db, "  testmarkt   nordstern! ").id == nord_id
    # Alias match.
    assert match_store(db, "Testmarkt Nord").id == nord_id
    # Postal code disambiguates a partial name to the right store.
    assert match_store(db, "Testmarkt", postal_code="99002").id == sued_id
    # An unrelated store stays below threshold -> no match (geocoding fallback).
    assert match_store(db, "Rewe City", "Berlin", "10115") is None

    db.close()


def test_match_store_in_text(catalog):
    nord_id, sued_id = catalog
    db = SessionLocal()

    # A full noisy OCR row resolves on the distinctive name token.
    line = "mo testmarkt nordstern 4711 teststr 1 99001 teststadt ekw 60"
    assert match_store_in_text(db, line, "99001").id == nord_id
    # A misread name still resolves when the postal code anchors it.
    assert (
        match_store_in_text(db, "mo testmarkt nrdstern langstr", "99001").id == nord_id
    )
    # A header row (no store token, no matching postal code) resolves to nothing.
    assert match_store_in_text(db, "tag markt nr strasse plz ort aufgaben min") is None
    # A postal code alone that matches nobody -> no match.
    assert match_store_in_text(db, "rewe fantasia nowhere", "12399") is None

    db.close()


def test_enrich_links_store_and_reads_through(catalog):
    """Enrichment links the store and fills plan data (tasks/minutes); the
    address and coordinate are never copied — they read through the store."""
    nord_id, _ = catalog
    db = SessionLocal()
    store = db.get(Store, nord_id)

    stop = Stop(customer="Testmarkt Nordstern", confidence={"street": 0.3})
    enrich_stop_from_store(stop, store)
    stop.store = store  # what the relationship would resolve to

    assert stop.store_id == nord_id
    # Nothing lands on the claim: it stays exactly what the plan printed.
    assert stop.claimed_street is None
    assert stop.claimed_geom is None
    # The effective views read the store's truth.
    assert stop.effective_street == "Teststr. 1"
    assert stop.effective_postal_code == "99001"
    assert stop.effective_geom is not None  # canonical coordinate, no geocoding
    assert stop.service_minutes == 75
    assert sorted(t.task_type for t in stop.tasks) == ["EKW", "Gaskuehler"]

    db.close()


def test_enrich_keeps_claim_and_plan_values(catalog):
    """The printed claim survives verbatim; the row's own tasks/minutes win."""
    nord_id, _ = catalog
    db = SessionLocal()
    store = db.get(Store, nord_id)

    stop = Stop(
        customer="Testmarkt Nordstern",
        claimed_street="Teststr. 99",  # what the paper printed
        claimed_postal_code="99001",
        claimed_city="Teststadt",
        service_minutes=90,
    )
    stop.tasks.append(Task(task_type="Fussmatten", raw_label="Fussmatten"))
    enrich_stop_from_store(stop, store)
    stop.store = store

    assert stop.claimed_street == "Teststr. 99"  # audit trail untouched
    assert stop.effective_street == "Teststr. 1"  # the store's verified street
    assert stop.service_minutes == 90  # not overwritten
    assert [t.task_type for t in stop.tasks] == ["Fussmatten"]  # defaults not added
    assert stop.store_id == nord_id

    db.close()
