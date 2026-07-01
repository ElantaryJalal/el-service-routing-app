from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class Stop(Base):
    __tablename__ = "stops"

    id: Mapped[int] = mapped_column(primary_key=True)
    tour_id: Mapped[int] = mapped_column(
        ForeignKey("tours.id", ondelete="CASCADE"), index=True, nullable=False
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[date | None] = mapped_column(Date)
    weekday: Mapped[str | None] = mapped_column(String)
    customer: Mapped[str | None] = mapped_column(String)
    order_no: Mapped[str | None] = mapped_column(String)
    street: Mapped[str | None] = mapped_column(String)
    postal_code: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    remarks_raw: Mapped[str | None] = mapped_column(Text)
    handwritten_notes: Mapped[str | None] = mapped_column(Text)
    # pending | done | rework | skip | unknown
    status_hint: Mapped[str] = mapped_column(
        String, nullable=False, server_default="unknown"
    )
    service_minutes: Mapped[int | None] = mapped_column(Integer)
    assigned_day: Mapped[date | None] = mapped_column(Date)
    sequence: Mapped[int | None] = mapped_column(Integer)
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    geom: Mapped[WKBElement | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False)
    )
    confidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # unconfirmed | confirmed | done
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="unconfirmed"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tour: Mapped["Tour"] = relationship(back_populates="stops")  # noqa: F821
    tasks: Mapped[list["Task"]] = relationship(  # noqa: F821
        back_populates="stop", cascade="all, delete-orphan"
    )
