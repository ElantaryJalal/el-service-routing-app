"""The office New-tour flow: blank create, manual stops, extract-into-tour,
duplicate detection on commit, stop deletion, and the tours list.

Requires a reachable database; network calls (geocoding, extraction, Overpass)
are monkeypatched.
"""

import pytest
from fastapi.testclient import TestClient

import app.api.tours as tours_api
from app.config import settings
from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.store import Store
from app.models.tour import Tour
from app.services.extraction import ExtractedStop, ExtractedTour


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")

client = TestClient(app)


@pytest.fixture
def cleanup_tours():
    created: list[int] = []
    yield created
    db = SessionLocal()
    for tour_id in created:
        db.query(Stop).filter(Stop.tour_id == tour_id).delete()
        db.query(Tour).filter(Tour.id == tour_id).delete()
    # Commit creates candidate stores for unmatched rows; drop the test ones.
    db.query(Store).filter(Store.name.in_(["Testmarkt", "Aldi A", "Aldi B"])).delete()
    db.commit()
    db.close()


def _create_tour() -> dict:
    resp = client.post(
        "/tours",
        json={
            "customer": "Aldi Nord",
            "calendar_week": 30,
            "date_from": "2026-07-20",
            "date_to": "2026-07-24",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_blank_tour_manual_stops_and_duplicate_commit(monkeypatch, cleanup_tours):
    monkeypatch.setattr(tours_api, "match_store", lambda *a, **k: None)
    # Distinct coordinate per street: a single shared point would put every
    # row within the 50 m proximity rule of the first created store.
    monkeypatch.setattr(
        tours_api,
        "geocode_address",
        lambda db, street, *a, **k: (
            12.37 + (abs(hash(street or "")) % 100) * 1e-2,
            51.34,
        ),
    )
    monkeypatch.setattr(tours_api, "fetch_opening_hours", lambda *a, **k: None)

    tour = _create_tour()
    cleanup_tours.append(tour["id"])
    assert tour["status"] == "draft"

    # The new tour shows up in the office list, filterable by status.
    listed = client.get("/tours", params={"status": "draft"})
    assert listed.status_code == 200
    assert tour["id"] in [t["id"] for t in listed.json()]

    # Two manual stops at the same address -> a duplicate pair, plus one other.
    stops = []
    for street in ("Markt 1", "Markt 1", "Andere Str. 5"):
        resp = client.post(
            f"/tours/{tour['id']}/stops",
            json={"customer": "Testmarkt", "street": street, "city": "Leipzig"},
        )
        assert resp.status_code == 201, resp.text
        stops.append(resp.json()["id"])

    draft = client.get(f"/tours/{tour['id']}/draft").json()
    assert [s["id"] for s in draft["stops"]] == stops
    assert draft["stops"][0]["customer"] == "Testmarkt"

    commit = client.post(f"/tours/{tour['id']}/commit")
    assert commit.status_code == 200, commit.text
    body = commit.json()
    assert body["status"] == "planned"
    assert body["duplicates"] == [[stops[0], stops[1]]]

    # Resolving the duplicate: delete one row; a re-commit is clean.
    assert client.delete(f"/stops/{stops[1]}").status_code == 204
    assert client.post(f"/tours/{tour['id']}/commit").json()["duplicates"] == []


def test_extract_into_existing_tour(monkeypatch, cleanup_tours):
    sample = ExtractedTour(
        customer="Aldi Nord",
        calendar_week=99,
        date_from="2020-01-01",
        date_to="2020-01-05",
        employee="Foto Mitarbeiter",
        stops=[
            ExtractedStop(customer="Aldi A", street="Astr. 1", city="Leipzig"),
            ExtractedStop(customer="Aldi B", street="Bstr. 2", city="Leipzig"),
        ],
    )
    monkeypatch.setattr(settings, "extraction_provider", "anthropic")
    monkeypatch.setattr(tours_api, "extract_tour", lambda data, mt: sample)
    monkeypatch.setattr(tours_api, "match_store", lambda *a, **k: None)
    monkeypatch.setattr(tours_api, "geocode_address", lambda *a, **k: None)

    tour = _create_tour()
    cleanup_tours.append(tour["id"])

    resp = client.post(
        "/tours/extract",
        data={"tour_id": str(tour["id"])},
        files={"image": ("plan.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    draft = resp.json()

    # Rows landed on the existing tour, no second tour created.
    assert draft["tour_id"] == tour["id"]
    assert [s["customer"] for s in draft["stops"]] == ["Aldi A", "Aldi B"]

    # The dispatcher's own header fields beat the photo's; blanks are filled.
    refreshed = client.get(f"/tours/{tour['id']}").json()
    assert refreshed["calendar_week"] == 30
    assert refreshed["date_from"] == "2026-07-20"
    db = SessionLocal()
    assert db.get(Tour, tour["id"]).employee == "Foto Mitarbeiter"
    db.close()

    # Extracting into a non-draft tour is refused.
    client.post(f"/tours/{tour['id']}/commit")
    resp = client.post(
        "/tours/extract",
        data={"tour_id": str(tour["id"])},
        files={"image": ("plan.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")},
    )
    assert resp.status_code == 409
