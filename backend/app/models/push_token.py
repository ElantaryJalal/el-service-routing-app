from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class PushToken(Base):
    """One device's Expo push token, owned by whoever is signed in on it.

    The token identifies the *installation*, not the person: registering a
    token that already exists moves it to the caller (a shared crew phone
    changing hands), and sign-out deletes it so a returned device stops
    receiving the previous owner's alerts. Delivery failures with
    DeviceNotRegistered prune rows server-side (app uninstalled).
    """

    __tablename__ = "push_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Expo push token, e.g. "ExponentPushToken[xxxxxxxx]".
    token: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    platform: Mapped[str | None] = mapped_column(String)  # "ios" | "android"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Bumped on every (re-)register, so stale installations are identifiable.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
