from datetime import date, datetime, time
from typing import Any

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base
from app.models.store import HoursSource


class Stop(Base):
    """One plan row. The linked store is the source of truth for address,
    coordinate, and hours; the stop keeps the plan's *claim* (claimed_*) as an
    audit trail of what the paper said. Consumers read location and hours
    through ``effective_geom`` / ``effective_hours`` — never the claim.
    """

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
    # What the printed plan said — audit data, never authoritative. Kept even
    # when it contradicts the store, so the office can see their plan was wrong.
    claimed_order_no: Mapped[str | None] = mapped_column(String)
    claimed_street: Mapped[str | None] = mapped_column(String)
    claimed_postal_code: Mapped[str | None] = mapped_column(String)
    claimed_city: Mapped[str | None] = mapped_column(String)
    remarks_raw: Mapped[str | None] = mapped_column(Text)
    handwritten_notes: Mapped[str | None] = mapped_column(Text)
    # pending | done | rework | skip | unknown
    status_hint: Mapped[str] = mapped_column(
        String, nullable=False, server_default="unknown"
    )
    # Manual service-time estimate in minutes (30–600). Range enforced at the
    # API layer, not the DB.
    service_minutes: Mapped[int | None] = mapped_column(Integer)
    assigned_day: Mapped[date | None] = mapped_column(Date)
    sequence: Mapped[int | None] = mapped_column(Integer)
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Why the stop is off the plan (optimiser verdict or manual removal), so
    # GET /tours/{id}/plan can rebuild the schedule without re-solving. Null
    # whenever assigned_day is set.
    unassigned_reason: Mapped[str | None] = mapped_column(String(120))
    # What the printed address geocoded to — diagnostic only. Routing always
    # goes through effective_geom, which prefers the store's geometry.
    claimed_geom: Mapped[WKBElement | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False)
    )
    # Did the plan's claimed address agree with the store's verified one?
    # Set during commit; null = not checked (e.g. no store linked yet).
    address_matches_store: Mapped[bool | None] = mapped_column(Boolean)
    # The dispatcher's verdict on a mismatch (POST /stops/{id}/resolve-address).
    # Durable across re-commits — the mismatch flag itself is recomputed each
    # commit, but a reviewed row must not resurface.
    address_review_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    address_review_resolved_by: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # unconfirmed | confirmed | done
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="unconfirmed"
    )
    # Source of truth for "done" (status/status_hint are display-oriented).
    # Set once via POST /stops/{id}/complete; re-completing is a no-op unless
    # forced.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Seeded/simulated content (inherits the tour's flag at seed time) —
    # excluded from management-facing queries unless explicitly requested.
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tour: Mapped["Tour"] = relationship(back_populates="stops")  # noqa: F821
    store: Mapped["Store | None"] = relationship()  # noqa: F821
    tasks: Mapped[list["Task"]] = relationship(  # noqa: F821
        back_populates="stop", cascade="all, delete-orphan"
    )

    # --- Read-through views: the store is the source of truth ----------------

    @property
    def effective_geom(self) -> WKBElement | None:
        """The authoritative coordinate: the linked store's geometry, and
        nothing else. claimed_geom is diagnostic and never routes anyone —
        a stop whose store has no geometry (or that has no store yet) has no
        routable location and belongs in the plan's unassigned list."""
        if self.store is not None:
            return self.store.geom
        return None

    @property
    def effective_hours(self) -> tuple[time | None, time | None]:
        """(opening, closing) from the linked store; (None, None) without one.
        Hours are a property of the shop, never of a plan row."""
        if self.store is not None:
            return (self.store.opening_time, self.store.closing_time)
        return (None, None)

    @property
    def effective_opening_time(self) -> time | None:
        return self.effective_hours[0]

    @property
    def effective_closing_time(self) -> time | None:
        return self.effective_hours[1]

    @property
    def effective_hours_source(self) -> HoursSource:
        if self.store is not None and self.store.hours_source is not None:
            return self.store.hours_source
        return HoursSource.default

    # The displayed/navigated address is the store's, verbatim — never mixed
    # with the claim. The claim only shows through for a stop with no store
    # at all (an unresolved row that cannot be navigated to anyway: its
    # lat/lng are null because effective_geom is store-only).

    @property
    def store_name(self) -> str | None:
        """The linked store's real name — the authoritative label for the
        stop. The printed ``customer`` claim can be generically wrong: some
        plans stamp the same chain name on every row (e.g. "ALDI NORD BEUCHA")
        even where the actual store is a different brand, so a card that trusts
        the claim mislabels the stop. Null when no store is linked."""
        if self.store is not None:
            return self.store.name
        return None

    @property
    def effective_street(self) -> str | None:
        if self.store is not None:
            return self.store.street
        return self.claimed_street

    @property
    def effective_postal_code(self) -> str | None:
        if self.store is not None:
            return self.store.postal_code
        return self.claimed_postal_code

    @property
    def effective_city(self) -> str | None:
        if self.store is not None:
            return self.store.city
        return self.claimed_city
