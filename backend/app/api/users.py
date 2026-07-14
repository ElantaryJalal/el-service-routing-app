"""Admin-only user management."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, require_role
from app.db import get_db
from app.models.user import Role, User
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.security import hash_password

# Managing users is admin-only; listing them is open to the office (the
# dispatcher's assignee dropdown, resolving assignee names in the tours list).
router = APIRouter(prefix="/users", tags=["users"])

_ADMIN = Depends(require_role(Role.admin))
_READERS = Depends(require_role(Role.manager, Role.dispatcher, Role.admin))


@router.post("", status_code=201, dependencies=[_ADMIN])
def create_user(body: UserCreate, db: Annotated[Session, Depends(get_db)]) -> UserRead:
    email = body.email.strip().lower()
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        name=body.name,
        role=body.role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A user with this email already exists"
        ) from None
    db.refresh(user)
    return UserRead.model_validate(user)


@router.get("", dependencies=[_READERS])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    role: Role | None = None,
) -> list[UserRead]:
    query = select(User).order_by(User.id)
    if role is not None:
        query = query.where(User.role == role)
    users = db.execute(query).scalars().all()
    return [UserRead.model_validate(u) for u in users]


@router.patch("/{user_id}", dependencies=[_ADMIN])
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> UserRead:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    updates = body.model_dump(exclude_unset=True)
    if user.id == current_user.id and (
        updates.get("is_active") is False
        or ("role" in updates and updates["role"] != Role.admin)
    ):
        raise HTTPException(
            status_code=400, detail="Admins cannot deactivate or demote themselves"
        )

    for field, value in updates.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)
