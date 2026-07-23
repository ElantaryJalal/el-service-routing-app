import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class DateMode(enum.StrEnum):
    """Whether stop dates from the plan are binding or a starting point.

    fixed: stops stay pinned to their printed plan date (Datum governs; the
    optimiser only sequences within each day). optimized: the optimiser may
    move stops between days.
    """

    fixed = "fixed"
    optimized = "optimized"


class TourStatus(enum.StrEnum):
    """Lifecycle of a tour.

    draft: extracted, awaiting confirmation. planned: confirmed/optimised,
    nobody assigned yet. assigned: a worker owns it. in_progress: first stop
    completed. done: every stop completed.
    """

    draft = "draft"
    planned = "planned"
    assigned = "assigned"
    in_progress = "in_progress"
    done = "done"


class Tour(Base):
    __tablename__ = "tours"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer: Mapped[str] = mapped_column(String, nullable=False)
    calendar_week: Mapped[int] = mapped_column(Integer, nullable=False)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    # Office metadata printed on the paper plan (Teamleiter / Mitarbeiter /
    # Team-Nr. / Fahrzeug). Stored and displayed verbatim; no logic hangs off
    # them. `employee` is provenance — the authoritative worker link is
    # assigned_user_id.
    team_lead: Mapped[str | None] = mapped_column(String)
    employee: Mapped[str | None] = mapped_column(String)
    team_no: Mapped[str | None] = mapped_column(String)
    vehicle: Mapped[str | None] = mapped_column(String)
    assigned_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[TourStatus] = mapped_column(
        SAEnum(
            TourStatus,
            name="tour_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=TourStatus.draft,
        server_default=TourStatus.draft.value,
    )
    date_mode: Mapped[DateMode] = mapped_column(
        SAEnum(
            DateMode,
            name="date_mode",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=DateMode.fixed,
        server_default=DateMode.fixed.value,
    )
    # Seeded/simulated content (demo driver, seed scripts, e2e users) —
    # excluded from management-facing queries unless explicitly requested.
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    assigned_user: Mapped["User | None"] = relationship()  # noqa: F821
    stops: Mapped[list["Stop"]] = relationship(  # noqa: F821
        back_populates="tour", cascade="all, delete-orphan"
    )
