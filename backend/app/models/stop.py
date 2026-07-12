import enum
from datetime import date, datetime, time
from typing import Any

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Time
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class HoursSource(enum.StrEnum):
    """Where a stop's opening/closing hours came from."""

    osm = "osm"
    manual = "manual"
    default = "default"


class Stop(Base):
    __tablename__ = "stops"

    id: Mapped[int] = mapped_column(primary_key=True)
    tour_id: Mapped[int] = mapped_column(
        ForeignKey("tours.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Set when the stop was matched to a catalog store (services.store_catalog);
    # links to canonical data and, later, per-store learned service times (P4).
    store_id: Mapped[int | None] = mapped_column(
        ForeignKey("stores.id", ondelete="SET NULL"), index=True
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
    # Manual service-time estimate in minutes (30–600). Range enforced at the
    # API layer, not the DB.
    service_minutes: Mapped[int | None] = mapped_column(Integer)
    # Single weekday opening/closing pair. The tour runs Mon–Fri and German
    # retail hours are near-uniform across weekdays, so one pair is enough for
    # now. Per-weekday hours are a future extension.
    opening_time: Mapped[time | None] = mapped_column(Time)
    # closing_time drives the "do it before it closes" feasibility check.
    closing_time: Mapped[time | None] = mapped_column(Time)
    hours_source: Mapped[HoursSource] = mapped_column(
        SAEnum(
            HoursSource,
            name="hours_source",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=HoursSource.default,
        server_default=HoursSource.default.value,
    )
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
    # Source of truth for "done" (status/status_hint are display-oriented).
    # Set once via POST /stops/{id}/complete; re-completing is a no-op unless
    # forced.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tour: Mapped["Tour"] = relationship(back_populates="stops")  # noqa: F821
    store: Mapped["Store | None"] = relationship()  # noqa: F821
    tasks: Mapped[list["Task"]] = relationship(  # noqa: F821
        back_populates="stop", cascade="all, delete-orphan"
    )
