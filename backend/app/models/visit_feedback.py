import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class FeedbackTag(enum.StrEnum):
    """Controlled vocabulary for visit feedback tags."""

    parking_full = "parking_full"
    access_problem = "access_problem"
    took_longer = "took_longer"
    store_condition = "store_condition"
    other = "other"


class VisitFeedback(Base):
    """Append-only field feedback the crew leaves after visiting a stop.

    Rows are never updated or deleted (the API exposes create + list only);
    they feed the learned service-time model (P4) and store attributes. The
    FKs are nullable with ON DELETE SET NULL so the history survives when a
    draft tour (and its stops) is deleted.
    """

    __tablename__ = "visit_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int | None] = mapped_column(
        ForeignKey("stores.id", ondelete="SET NULL"), index=True
    )
    tour_id: Mapped[int | None] = mapped_column(
        ForeignKey("tours.id", ondelete="SET NULL"), index=True
    )
    stop_id: Mapped[int | None] = mapped_column(
        ForeignKey("stops.id", ondelete="SET NULL"), index=True
    )
    employee: Mapped[str | None] = mapped_column(String)
    # Values come from FeedbackTag; enforced at the API layer, not the DB.
    tags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    note: Mapped[str | None] = mapped_column(Text)
    photo_path: Mapped[str | None] = mapped_column(String)
    # Client-generated idempotency key: offline sync may retry the same POST,
    # which must not create a second row.
    client_uuid: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
