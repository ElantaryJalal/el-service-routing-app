import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
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


class Tour(Base):
    __tablename__ = "tours"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer: Mapped[str] = mapped_column(String, nullable=False)
    calendar_week: Mapped[int] = mapped_column(Integer, nullable=False)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    team_lead: Mapped[str | None] = mapped_column(String)
    employee: Mapped[str | None] = mapped_column(String)
    vehicle: Mapped[str | None] = mapped_column(String)
    hotel_id: Mapped[int | None] = mapped_column(
        ForeignKey("hotels.id", ondelete="SET NULL")
    )
    # draft | confirmed
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="draft")
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    hotel: Mapped["Hotel | None"] = relationship(back_populates="tours")  # noqa: F821
    stops: Mapped[list["Stop"]] = relationship(  # noqa: F821
        back_populates="tour", cascade="all, delete-orphan"
    )
