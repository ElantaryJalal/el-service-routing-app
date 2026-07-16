"""Learned service durations per (store, service profile).

One store is not one duration: different task profiles — often different
teams — take very different time at the same market (a full deep-clean vs. a
45-minute maintenance visit). The P4 learner therefore keys its results by
the visit's *task signature* alongside the store-wide median kept on the
store row (which stays as the fallback for rows whose tasks match nothing
learned yet).
"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


def task_signature(task_types: Iterable[str | None]) -> str:
    """Canonical key for a visit's service profile: the deduped, sorted,
    case-folded task types. Empty string = a visit with no recorded tasks
    (itself a valid, learnable profile)."""
    return "+".join(sorted({(t or "").strip().casefold() for t in task_types} - {""}))


class StoreServiceTime(Base):
    __tablename__ = "store_service_times"
    __table_args__ = (
        UniqueConstraint("store_id", "task_signature", name="uq_store_service_profile"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), index=True, nullable=False
    )
    task_signature: Mapped[str] = mapped_column(String, nullable=False)
    # Human-readable form of the profile (first-seen raw task labels).
    tasks_label: Mapped[str | None] = mapped_column(String)
    # Median observed duration; null while samples < MIN_SAMPLES.
    learned_minutes: Mapped[int | None] = mapped_column(Integer)
    samples: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    store: Mapped["Store"] = relationship(back_populates="service_times")  # noqa: F821
