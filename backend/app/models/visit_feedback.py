import enum
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
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
    # Seeded/simulated content (demo driver, e2e users, "(Demo)" notes) —
    # excluded from management-facing queries unless explicitly requested.
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    store: Mapped["Store | None"] = relationship()  # noqa: F821

    # Feedback is shown to people, never as a raw store id: expose the store's
    # display identity for the read schema (None when the store is gone).
    @property
    def store_name(self) -> str | None:
        return self.store.name if self.store else None

    @property
    def store_city(self) -> str | None:
        return self.store.city if self.store else None

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def dedupe_feedback(rows: Iterable[VisitFeedback]) -> list[VisitFeedback]:
    """Collapse exact duplicates — same store, author, note text, and
    timestamp — to a single entry (offline-sync retries and seed scripts
    produce them)."""
    unique: list[VisitFeedback] = []
    seen: set[tuple] = set()
    for row in rows:
        key = (row.store_id, row.employee, row.note, row.created_at)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique
