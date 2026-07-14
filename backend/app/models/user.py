import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, true
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class Role(enum.StrEnum):
    """Access level of a user account.

    worker: field employee servicing stops. dispatcher: plans and edits tours.
    manager: office oversight. admin: full access incl. user management.
    """

    worker = "worker"
    dispatcher = "dispatcher"
    manager = "manager"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[Role] = mapped_column(
        SAEnum(
            Role,
            name="user_role",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
