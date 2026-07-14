"""Auth dependencies: current-user resolution and role guards.

Gate a whole router with
``APIRouter(..., dependencies=[Depends(require_role(Role.admin))])`` or a
single endpoint with ``user: Annotated[User, Depends(require_role(...))]``.
"""

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.stop import Stop
from app.models.tour import Tour, TourStatus
from app.models.user import Role, User
from app.security import decode_access_token

# Tours a worker is currently on: what GET /me/tours lists.
ACTIVE_TOUR_STATUSES = (TourStatus.assigned, TourStatus.in_progress)
# Access additionally covers the worker's just-finished tours: completing the
# last stop flips the tour to done, and the map reload / completion undo /
# after-visit feedback that follow must not suddenly 403.
_WORKER_ACCESS_STATUSES = (*ACTIVE_TOUR_STATUSES, TourStatus.done)

# auto_error=False so we control the 401 body and WWW-Authenticate header.
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise _unauthorized("Not authenticated")

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise _unauthorized("Invalid or expired token") from None

    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized("Invalid or expired token")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is deactivated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: Role) -> Callable[..., User]:
    """Dependency factory: 401 if unauthenticated, 403 if the role isn't allowed."""

    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return dependency


def _is_own_active_tour(user: User, tour: Tour) -> bool:
    return tour.assigned_user_id == user.id and tour.status in _WORKER_ACCESS_STATUSES


def ensure_tour_visible(user: User, tour: Tour) -> None:
    """Read access to a tour: office roles see all, workers only their own
    currently-assigned tours. Raises 403 otherwise."""
    if user.role in (Role.manager, Role.dispatcher, Role.admin):
        return
    if _is_own_active_tour(user, tour):
        return
    raise HTTPException(status_code=403, detail="Not your tour")


def ensure_tour_workable(user: User, tour: Tour) -> None:
    """Field-work mutations (completion, feedback): dispatcher/admin anywhere,
    workers only on their own active tours. Managers are read-only."""
    if user.role in (Role.dispatcher, Role.admin):
        return
    if user.role == Role.worker and _is_own_active_tour(user, tour):
        return
    raise HTTPException(status_code=403, detail="Not your tour")


def worker_services_store(db: Session, user: User, store_id: int) -> bool:
    """Whether the store appears on one of the worker's active tours."""
    return (
        db.scalar(
            select(Stop.id)
            .join(Tour, Stop.tour_id == Tour.id)
            .where(
                Stop.store_id == store_id,
                Tour.assigned_user_id == user.id,
                Tour.status.in_(_WORKER_ACCESS_STATUSES),
            )
            .limit(1)
        )
        is not None
    )
