from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    hotel: Mapped["Hotel | None"] = relationship(back_populates="tours")  # noqa: F821
    stops: Mapped[list["Stop"]] = relationship(  # noqa: F821
        back_populates="tour", cascade="all, delete-orphan"
    )
