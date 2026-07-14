"""Integration tests for login, /auth/me, and admin-only user management.

Requires a reachable database with migrations applied (see infra/README.md).
Skipped automatically when the DB is unreachable. All users created here use
@authtest.elservice.de emails and are deleted in fixture teardown.
"""

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal, engine
from app.main import app
from app.models.user import Role, User
from app.security import hash_password

# Exercise the real token/guard stack (see conftest._auth_override).
USE_REAL_AUTH = True

# A syntactically real domain: EmailStr rejects special-use TLDs like .local.
TEST_DOMAIN = "authtest.elservice.de"
ADMIN_EMAIL = f"admin@{TEST_DOMAIN}"
ADMIN_PASSWORD = "adminpass123"


def _db_reachable() -> bool:
    try:
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="database not reachable")

client = TestClient(app)


@pytest.fixture
def admin_user():
    """A seeded admin; teardown removes every @authtest.elservice.de user."""
    db = SessionLocal()
    admin = User(
        email=ADMIN_EMAIL,
        password_hash=hash_password(ADMIN_PASSWORD),
        name="Test Admin",
        role=Role.admin,
    )
    db.add(admin)
    db.commit()
    admin_id = admin.id
    db.close()

    yield admin_id

    db = SessionLocal()
    db.query(User).filter(User.email.like(f"%@{TEST_DOMAIN}")).delete(
        synchronize_session=False
    )
    db.commit()
    db.close()


def _login(email: str, password: str):
    return client.post("/auth/login", json={"email": email, "password": password})


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _admin_token() -> str:
    resp = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_login_ok(admin_user):
    resp = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "admin"
    assert "password_hash" not in body["user"]


def test_login_bad_credentials(admin_user):
    assert _login(ADMIN_EMAIL, "wrong-password").status_code == 401
    assert _login(f"nobody@{TEST_DOMAIN}", "whatever").status_code == 401


def test_me(admin_user):
    token = _admin_token()
    resp = client.get("/auth/me", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == ADMIN_EMAIL
    assert body["role"] == "admin"
    assert "password_hash" not in body

    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers=_auth("garbage")).status_code == 401


def test_admin_creates_dispatcher_and_worker(admin_user):
    token = _admin_token()
    for role in ("dispatcher", "worker"):
        resp = client.post(
            "/users",
            headers=_auth(token),
            json={
                "email": f"{role}@{TEST_DOMAIN}",
                "password": "secret-pass-1",
                "name": role.title(),
                "role": role,
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["role"] == role

    # The new dispatcher can log in and /auth/me reports the right role.
    resp = _login(f"dispatcher@{TEST_DOMAIN}", "secret-pass-1")
    assert resp.status_code == 200, resp.text
    me = client.get("/auth/me", headers=_auth(resp.json()["access_token"]))
    assert me.json()["role"] == "dispatcher"


def test_users_requires_admin(admin_user):
    token = _admin_token()
    resp = client.post(
        "/users",
        headers=_auth(token),
        json={
            "email": f"worker2@{TEST_DOMAIN}",
            "password": "secret-pass-1",
            "name": "Worker Two",
            "role": "worker",
        },
    )
    assert resp.status_code == 201, resp.text

    worker_token = _login(f"worker2@{TEST_DOMAIN}", "secret-pass-1").json()[
        "access_token"
    ]
    assert client.get("/users", headers=_auth(worker_token)).status_code == 403
    assert client.get("/users").status_code == 401

    admin_list = client.get("/users", headers=_auth(token))
    assert admin_list.status_code == 200
    assert any(u["email"] == ADMIN_EMAIL for u in admin_list.json())


def test_duplicate_email_conflict(admin_user):
    token = _admin_token()
    payload = {
        "email": f"dup@{TEST_DOMAIN}",
        "password": "secret-pass-1",
        "name": "Dup",
        "role": "worker",
    }
    assert client.post("/users", headers=_auth(token), json=payload).status_code == 201
    assert client.post("/users", headers=_auth(token), json=payload).status_code == 409


def test_patch_user(admin_user):
    token = _admin_token()
    created = client.post(
        "/users",
        headers=_auth(token),
        json={
            "email": f"patchme@{TEST_DOMAIN}",
            "password": "secret-pass-1",
            "name": "Patch Me",
            "role": "worker",
        },
    )
    user_id = created.json()["id"]

    resp = client.patch(
        f"/users/{user_id}",
        headers=_auth(token),
        json={"name": "Patched", "role": "dispatcher", "is_active": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Patched"
    assert body["role"] == "dispatcher"
    assert body["is_active"] is False

    # Deactivated users cannot log in.
    assert _login(f"patchme@{TEST_DOMAIN}", "secret-pass-1").status_code == 401

    assert (
        client.patch("/users/999999", headers=_auth(token), json={}).status_code == 404
    )


def test_admin_cannot_demote_or_deactivate_self(admin_user):
    token = _admin_token()
    for payload in ({"is_active": False}, {"role": "worker"}):
        resp = client.patch(f"/users/{admin_user}", headers=_auth(token), json=payload)
        assert resp.status_code == 400, resp.text
