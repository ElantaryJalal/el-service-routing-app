"""Push tokens and assignment alerts (P4 follow-up).

Acceptance: a worker's device registers its Expo token; assigning a tour
pushes "New tour assigned" to that device; reassigning notifies both workers;
unassigning notifies the displaced worker; sign-out (DELETE) stops the
alerts; a DeviceNotRegistered ticket prunes the token.

The Expo transport (`app.services.push._post_messages`) is monkeypatched —
no network. Requires a reachable database with migrations applied.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.db import SessionLocal, engine
from app.main import app
from app.models.push_token import PushToken
from app.models.tour import Tour, TourStatus
from app.models.user import Role, User
from app.services import push as push_service
from app.services.push import notify_user

TEST_DOMAIN = "pushtest.elservice.de"


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
    """Two workers and one planned tour; teardown removes everything."""
    db = SessionLocal()
    workers = [
        User(
            email=f"worker{i}@{TEST_DOMAIN}",
            password_hash="!",
            name=f"Push Worker {i}",
            role=Role.worker,
        )
        for i in (1, 2)
    ]
    tour = Tour(
        customer="Push Test Tour",
        calendar_week=12,
        date_from=date(2027, 3, 22),
        date_to=date(2027, 3, 26),
        status=TourStatus.planned,
    )
    db.add_all([*workers, tour])
    db.commit()
    for obj in (*workers, tour):
        db.refresh(obj)

    yield {"workers": workers, "tour": tour}

    db.query(PushToken).filter(PushToken.user_id.in_([w.id for w in workers])).delete()
    db.query(Tour).filter(Tour.id == tour.id).delete()
    db.query(User).filter(User.email.like(f"%@{TEST_DOMAIN}")).delete(
        synchronize_session=False
    )
    db.commit()
    db.close()


@pytest.fixture
def outbox(monkeypatch):
    """Captures Expo batches; each message is accepted with an 'ok' ticket."""
    sent: list[dict] = []

    def fake_post(messages):
        sent.extend(messages)
        return [{"status": "ok"} for _ in messages]

    monkeypatch.setattr(push_service, "_post_messages", fake_post)
    return sent


def _register(token: str, platform: str = "android") -> None:
    resp = client.post("/me/push-tokens", json={"token": token, "platform": platform})
    assert resp.status_code == 204


def _token_rows(token: str) -> list[PushToken]:
    with SessionLocal() as db:
        return list(db.query(PushToken).filter(PushToken.token == token))


def test_register_is_idempotent_and_moves_between_users(world):
    # push_tokens.user_id is a real FK, so run these requests as the fixture
    # workers instead of conftest's transient (id 0) override admin.
    worker1, worker2 = world["workers"]

    app.dependency_overrides[get_current_user] = lambda: worker1
    _register("ExponentPushToken[push-test-1]")
    _register("ExponentPushToken[push-test-1]", platform="ios")
    rows = _token_rows("ExponentPushToken[push-test-1]")
    assert len(rows) == 1
    assert rows[0].platform == "ios"
    assert rows[0].user_id == worker1.id

    # The crew phone changes hands: worker2 signs in on the same device.
    app.dependency_overrides[get_current_user] = lambda: worker2
    _register("ExponentPushToken[push-test-1]")
    rows = _token_rows("ExponentPushToken[push-test-1]")
    assert len(rows) == 1
    assert rows[0].user_id == worker2.id

    # worker1's stale sign-out must not delete worker2's registration...
    app.dependency_overrides[get_current_user] = lambda: worker1
    client.delete("/me/push-tokens", params={"token": "ExponentPushToken[push-test-1]"})
    assert len(_token_rows("ExponentPushToken[push-test-1]")) == 1

    # ...but the owner's sign-out does.
    app.dependency_overrides[get_current_user] = lambda: worker2
    client.delete("/me/push-tokens", params={"token": "ExponentPushToken[push-test-1]"})
    assert _token_rows("ExponentPushToken[push-test-1]") == []


def test_assign_reassign_unassign_notify_the_right_workers(world, outbox):
    worker1, worker2 = world["workers"]
    tour = world["tour"]
    with SessionLocal() as db:
        db.add(PushToken(user_id=worker1.id, token="ExponentPushToken[push-w1]"))
        db.add(PushToken(user_id=worker2.id, token="ExponentPushToken[push-w2]"))
        db.commit()

    # Assign to worker1: exactly one push, to worker1's device.
    resp = client.post(f"/tours/{tour.id}/assign", json={"user_id": worker1.id})
    assert resp.status_code == 200
    assert [m["to"] for m in outbox] == ["ExponentPushToken[push-w1]"]
    assert outbox[0]["title"] == "New tour assigned"
    assert outbox[0]["data"] == {"tour_id": tour.id}
    assert "Push Test Tour" in outbox[0]["body"]

    # Re-assign to the same worker: no duplicate alert.
    outbox.clear()
    client.post(f"/tours/{tour.id}/assign", json={"user_id": worker1.id})
    assert outbox == []

    # Reassign to worker2: worker2 gets the tour, worker1 learns it moved.
    outbox.clear()
    client.post(f"/tours/{tour.id}/assign", json={"user_id": worker2.id})
    by_token = {m["to"]: m for m in outbox}
    assert set(by_token) == {
        "ExponentPushToken[push-w1]",
        "ExponentPushToken[push-w2]",
    }
    assert by_token["ExponentPushToken[push-w2]"]["title"] == "New tour assigned"
    assert by_token["ExponentPushToken[push-w1]"]["title"] == "Tour reassigned"

    # Unassign: the displaced worker is told.
    outbox.clear()
    client.post(f"/tours/{tour.id}/unassign")
    assert [m["to"] for m in outbox] == ["ExponentPushToken[push-w2]"]
    assert outbox[0]["title"] == "Tour unassigned"


def test_dead_device_token_is_pruned(world, monkeypatch):
    worker1 = world["workers"][0]
    with SessionLocal() as db:
        db.add(PushToken(user_id=worker1.id, token="ExponentPushToken[push-dead]"))
        db.commit()

    monkeypatch.setattr(
        push_service,
        "_post_messages",
        lambda messages: [
            {"status": "error", "details": {"error": "DeviceNotRegistered"}}
            for _ in messages
        ],
    )
    assert notify_user(worker1.id, "t", "b") == 0
    assert _token_rows("ExponentPushToken[push-dead]") == []


def test_push_failure_never_raises(world, monkeypatch):
    worker1 = world["workers"][0]
    with SessionLocal() as db:
        db.add(PushToken(user_id=worker1.id, token="ExponentPushToken[push-err]"))
        db.commit()

    def boom(messages):
        raise RuntimeError("expo is down")

    monkeypatch.setattr(push_service, "_post_messages", boom)
    assert notify_user(worker1.id, "t", "b") == 0  # swallowed, not raised
    assert len(_token_rows("ExponentPushToken[push-err]")) == 1


def test_notify_user_without_tokens_sends_nothing(world, outbox):
    assert notify_user(world["workers"][1].id, "t", "b") == 0
    assert outbox == []
