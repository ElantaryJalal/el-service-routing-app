"""Role-based access across the tour lifecycle.

Acceptance: a worker sees and works only its own assigned tours; a dispatcher
assigns; a manager reads everything but mutates nothing. Uses real tokens.

Requires a reachable database with migrations applied; skipped otherwise.
"""

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models.stop import Stop
from app.models.store import Store
from app.models.tour import Tour, TourStatus
from app.models.user import Role, User
from app.models.visit_feedback import VisitFeedback
from app.security import hash_password

# Exercise the real token/guard stack (see conftest._auth_override).
USE_REAL_AUTH = True

TEST_DOMAIN = "rbactest.elservice.de"
PASSWORD = "rbac-pass-123"


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
    """Four users (dispatcher/manager/two workers), two planned tours with two
    stops each, and a store linked to tour 1's first stop."""
    db = SessionLocal()

    users = {}
    for role in (Role.dispatcher, Role.manager, Role.worker, Role.worker):
        key = (
            role.value
            if role != Role.worker
            else ("worker1" if "worker1" not in users else "worker2")
        )
        user = User(
            email=f"{key}@{TEST_DOMAIN}",
            password_hash=hash_password(PASSWORD),
            name=key.title(),
            role=role,
        )
        db.add(user)
        users[key] = user
    db.flush()

    store = Store(name="RBAC Test Store")
    db.add(store)
    db.flush()

    tours = {}
    for key in ("tour1", "tour2"):
        tour = Tour(
            customer="Aldi Nord",
            calendar_week=29,
            date_from=date(2026, 7, 13),
            date_to=date(2026, 7, 17),
            status=TourStatus.planned,
        )
        db.add(tour)
        db.flush()
        for i in range(2):
            db.add(
                Stop(
                    tour_id=tour.id,
                    row_index=i,
                    customer=f"Market {i}",
                    status="confirmed",
                    store_id=store.id if key == "tour1" and i == 0 else None,
                )
            )
        tours[key] = tour
    db.commit()

    ids = {
        "users": {k: u.id for k, u in users.items()},
        "tours": {k: t.id for k, t in tours.items()},
        "store": store.id,
    }
    tour_ids = [t.id for t in tours.values()]
    db.close()

    yield ids

    db = SessionLocal()
    db.query(VisitFeedback).filter(VisitFeedback.tour_id.in_(tour_ids)).delete(
        synchronize_session=False
    )
    db.query(Stop).filter(Stop.tour_id.in_(tour_ids)).delete(synchronize_session=False)
    db.query(Tour).filter(Tour.id.in_(tour_ids)).delete(synchronize_session=False)
    db.query(Store).filter(Store.id == ids["store"]).delete(synchronize_session=False)
    db.query(User).filter(User.email.like(f"%@{TEST_DOMAIN}")).delete(
        synchronize_session=False
    )
    db.commit()
    db.close()


def _token(key: str) -> str:
    resp = client.post(
        "/auth/login", json={"email": f"{key}@{TEST_DOMAIN}", "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _stop_ids(db_tour_id: int, token: str) -> list[int]:
    resp = client.get(f"/tours/{db_tour_id}/stops", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return [s["id"] for s in resp.json()]


def _assign(tour_id: int, user_id: int, token: str):
    return client.post(
        f"/tours/{tour_id}/assign", headers=_auth(token), json={"user_id": user_id}
    )


def test_dispatcher_assigns_and_worker_scope(world):
    dispatcher = _token("dispatcher")
    tour1, tour2 = world["tours"]["tour1"], world["tours"]["tour2"]
    w1_id, w2_id = world["users"]["worker1"], world["users"]["worker2"]

    # Dispatcher assigns each tour to its worker.
    resp = _assign(tour1, w1_id, dispatcher)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "assigned"
    assert resp.json()["assigned_user_id"] == w1_id
    assert _assign(tour2, w2_id, dispatcher).status_code == 200

    worker1 = _token("worker1")

    # /me/tours lists exactly the worker's own active tours.
    mine = client.get("/me/tours", headers=_auth(worker1))
    assert mine.status_code == 200
    assert [t["id"] for t in mine.json()] == [tour1]

    # Own tour readable; the other worker's tour is not.
    assert client.get(f"/tours/{tour1}", headers=_auth(worker1)).status_code == 200
    assert client.get(f"/tours/{tour1}/plan", headers=_auth(worker1)).status_code == 200
    assert client.get(f"/tours/{tour2}", headers=_auth(worker1)).status_code == 403
    assert (
        client.get(f"/tours/{tour2}/stops", headers=_auth(worker1)).status_code == 403
    )

    # Planning surface is 403 for workers.
    assert (
        client.post(f"/tours/{tour1}/optimise", headers=_auth(worker1)).status_code
        == 403
    )
    assert (
        client.post(f"/tours/{tour1}/commit", headers=_auth(worker1)).status_code == 403
    )
    assert _assign(tour1, w1_id, worker1).status_code == 403
    assert (
        client.post(f"/tours/{tour1}/unassign", headers=_auth(worker1)).status_code
        == 403
    )
    assert (
        client.patch(
            f"/tours/{tour1}", headers=_auth(worker1), json={"date_mode": "optimized"}
        ).status_code
        == 403
    )

    # Unauthenticated is 401 everywhere.
    assert client.get("/me/tours").status_code == 401
    assert client.get(f"/tours/{tour1}").status_code == 401


def test_completion_drives_lifecycle_and_ownership(world):
    dispatcher = _token("dispatcher")
    tour1, tour2 = world["tours"]["tour1"], world["tours"]["tour2"]
    w1_id, w2_id = world["users"]["worker1"], world["users"]["worker2"]
    assert _assign(tour1, w1_id, dispatcher).status_code == 200
    assert _assign(tour2, w2_id, dispatcher).status_code == 200

    worker1 = _token("worker1")
    own_stops = _stop_ids(tour1, worker1)
    other_stops = _stop_ids(tour2, dispatcher)

    def tour_status(tour_id: int) -> str:
        return client.get(f"/tours/{tour_id}", headers=_auth(dispatcher)).json()[
            "status"
        ]

    # Another worker's stop: 403 and no state change.
    assert (
        client.post(
            f"/stops/{other_stops[0]}/complete", headers=_auth(worker1)
        ).status_code
        == 403
    )
    assert tour_status(tour2) == "assigned"

    # First own completion -> in_progress; all done -> done.
    assert (
        client.post(
            f"/stops/{own_stops[0]}/complete", headers=_auth(worker1)
        ).status_code
        == 200
    )
    assert tour_status(tour1) == "in_progress"
    assert (
        client.post(
            f"/stops/{own_stops[1]}/complete", headers=_auth(worker1)
        ).status_code
        == 200
    )
    assert tour_status(tour1) == "done"

    # Undo on the worker's just-finished tour still works and steps back.
    assert (
        client.delete(
            f"/stops/{own_stops[1]}/complete", headers=_auth(worker1)
        ).status_code
        == 200
    )
    assert tour_status(tour1) == "in_progress"
    assert (
        client.delete(
            f"/stops/{own_stops[0]}/complete", headers=_auth(worker1)
        ).status_code
        == 200
    )
    assert tour_status(tour1) == "assigned"

    # Feedback: own stop 201 with the authenticated name; other's stop 403.
    resp = client.post(
        "/feedback",
        headers=_auth(worker1),
        json={"stop_id": own_stops[0], "client_uuid": str(uuid4()), "tags": []},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["employee"] == "Worker1"
    resp = client.post(
        "/feedback",
        headers=_auth(worker1),
        json={"stop_id": other_stops[0], "client_uuid": str(uuid4()), "tags": []},
    )
    assert resp.status_code == 403

    # Store attributes: on the worker's tour 200, elsewhere the store is 403.
    resp = client.patch(
        f"/stores/{world['store']}/attributes",
        headers=_auth(worker1),
        json={"in_mall": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["attributes_updated_by"] == "Worker1"
    worker2 = _token("worker2")
    assert (
        client.patch(
            f"/stores/{world['store']}/attributes",
            headers=_auth(worker2),
            json={"in_mall": True},
        ).status_code
        == 403
    )


def test_worker_reschedules_own_stop_only(world):
    dispatcher = _token("dispatcher")
    tour1, tour2 = world["tours"]["tour1"], world["tours"]["tour2"]
    w1_id, w2_id = world["users"]["worker1"], world["users"]["worker2"]
    assert _assign(tour1, w1_id, dispatcher).status_code == 200
    assert _assign(tour2, w2_id, dispatcher).status_code == 200

    worker1 = _token("worker1")
    own_stop = _stop_ids(tour1, worker1)[0]
    other_stop = _stop_ids(tour2, dispatcher)[0]
    tuesday = "2026-07-14"

    # A worker can move a stop's day on their own active tour.
    resp = client.patch(
        f"/stops/{own_stop}/plan",
        headers=_auth(worker1),
        json={"assigned_day": tuesday},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assigned_day"] == tuesday

    # But not on another worker's tour.
    assert (
        client.patch(
            f"/stops/{other_stop}/plan",
            headers=_auth(worker1),
            json={"assigned_day": tuesday},
        ).status_code
        == 403
    )

    # A day outside the tour's range is rejected (not silently clamped).
    assert (
        client.patch(
            f"/stops/{own_stop}/plan",
            headers=_auth(worker1),
            json={"assigned_day": "2026-08-01"},
        ).status_code
        == 422
    )


def test_manager_is_read_only(world):
    dispatcher = _token("dispatcher")
    manager = _token("manager")
    tour1 = world["tours"]["tour1"]
    w1_id = world["users"]["worker1"]
    assert _assign(tour1, w1_id, dispatcher).status_code == 200
    stop_id = _stop_ids(tour1, manager)[0]

    # Reads are open to the manager.
    assert client.get(f"/tours/{tour1}", headers=_auth(manager)).status_code == 200
    assert client.get(f"/tours/{tour1}/plan", headers=_auth(manager)).status_code == 200
    assert client.get("/stores", headers=_auth(manager)).status_code == 200
    assert client.get("/feedback", headers=_auth(manager)).status_code == 200
    assert (
        client.get(
            f"/stores/{world['store']}/visits", headers=_auth(manager)
        ).status_code
        == 200
    )

    # Mutations are not.
    assert (
        client.post(f"/tours/{tour1}/optimise", headers=_auth(manager)).status_code
        == 403
    )
    assert (
        client.patch(
            f"/stops/{stop_id}/plan",
            headers=_auth(manager),
            json={"assigned_day": "2026-07-14"},
        ).status_code
        == 403
    )
    assert _assign(tour1, w1_id, manager).status_code == 403
    assert (
        client.post(f"/stops/{stop_id}/complete", headers=_auth(manager)).status_code
        == 403
    )
    assert (
        client.patch(
            f"/stores/{world['store']}/attributes",
            headers=_auth(manager),
            json={"in_mall": True},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/feedback",
            headers=_auth(manager),
            json={"stop_id": stop_id, "client_uuid": str(uuid4()), "tags": []},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/stores/service-times/recompute", headers=_auth(manager)
        ).status_code
        == 403
    )


def test_assign_guards(world):
    dispatcher = _token("dispatcher")
    tour1 = world["tours"]["tour1"]
    w1_id = world["users"]["worker1"]

    # Unknown assignee.
    assert _assign(tour1, 999999, dispatcher).status_code == 404

    # Unassign returns an untouched assigned tour to planned.
    assert _assign(tour1, w1_id, dispatcher).status_code == 200
    resp = client.post(f"/tours/{tour1}/unassign", headers=_auth(dispatcher))
    assert resp.status_code == 200
    assert resp.json()["status"] == "planned"
    assert resp.json()["assigned_user_id"] is None
