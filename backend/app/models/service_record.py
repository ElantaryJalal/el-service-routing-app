"""The service ledger: one row per service actually performed at a store.

Each record links the store, the tour, the responsible team (the tour's
assigned user, plus the plan's employee name as a display fallback), the
visit's tasks, and the *derived* duration — completion timestamps minus the
OSRM drive leg, as computed by the P4 learner (services.service_times, which
rebuilds this ledger on every recompute).

Everything the office sees about time spent is an aggregate of these rows:
the store list's total time, the store detail's per-service history, and the
learned estimates (medians per store / per task profile) that feed new plans.
"""

from collections.abc import Iterable
from datetime import date, datetime
from statistics import median

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base

# An estimate is only trusted once this many services back it.
MIN_SAMPLES = 2


def task_signature(task_types: Iterable[str | None]) -> str:
    """Canonical key for a visit's service profile: the deduped, sorted,
    case-folded task types. Empty string = a visit with no recorded tasks
    (itself a valid, learnable profile)."""
    return "+".join(sorted({(t or "").strip().casefold() for t in task_types} - {""}))


def learned_minutes(durations: list[int]) -> int | None:
    """The estimate a set of recorded durations supports: their median, or
    None below MIN_SAMPLES."""
    if len(durations) < MIN_SAMPLES:
        return None
    return int(round(median(durations)))


class ServiceRecord(Base):
    __tablename__ = "service_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    # One record per completed stop whose duration could be derived.
    stop_id: Mapped[int] = mapped_column(
        ForeignKey("stops.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tour_id: Mapped[int] = mapped_column(
        ForeignKey("tours.id", ondelete="CASCADE"), nullable=False
    )
    # The team responsible: the tour's assigned user when there is one …
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # … and always a display name (assigned user's name, or the plan's
    # employee/team-lead text for history imported before user accounts).
    team: Mapped[str | None] = mapped_column(String)
    serviced_on: Mapped[date | None] = mapped_column(Date)
    task_signature: Mapped[str] = mapped_column(String, nullable=False, default="")
    tasks_label: Mapped[str | None] = mapped_column(String)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Seeded/simulated content (demo driver, seed scripts, e2e users) —
    # excluded from management-facing queries unless explicitly requested.
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    store: Mapped["Store"] = relationship(  # noqa: F821
        back_populates="service_records"
    )
