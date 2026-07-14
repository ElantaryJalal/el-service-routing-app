"""Shared test setup: bypass auth for business-logic tests.

Every endpoint is role-guarded, but most tests exercise routing/extraction
logic, not access control. An autouse fixture overrides get_current_user with
a transient admin, so those tests run unchanged. Modules that test the real
auth stack (tokens, role guards) opt out by setting, at module level::

    USE_REAL_AUTH = True
"""

import pytest

from app.api.deps import get_current_user
from app.main import app
from app.models.user import Role, User


@pytest.fixture(autouse=True)
def _auth_override(request):
    if getattr(request.module, "USE_REAL_AUTH", False):
        yield
        return

    override_user = User(
        id=0,
        email="override@authtest.elservice.de",
        password_hash="!",
        name="Test Override Admin",
        role=Role.admin,
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: override_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
