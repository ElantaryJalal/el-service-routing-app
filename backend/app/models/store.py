import enum
from datetime import datetime, time

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import Boolean, DateTime, Integer, String, Time
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class StoreSize(enum.StrEnum):
    small = "small"
    medium = "medium"
    large = "large"


class HoursSource(enum.StrEnum):
    """Where the store's opening/closing hours came from."""

    osm = "osm"
    manual = "manual"
    default = "default"


class AddressProvenance(enum.StrEnum):
    """How trustworthy the store's address is, from weakest to strongest."""

    printed = "printed"  # copied off a plan, never checked
    geocoded = "geocoded"  # resolved by a geocoder
    verified = "verified"  # checked by the office
    field_confirmed = "field_confirmed"  # confirmed on site by the crew


class GeomProvenance(enum.StrEnum):
    geocoded = "geocoded"
    verified = "verified"
    field_confirmed = "field_confirmed"


class Store(Base):
    """Canonical catalog of the ~26 supermarkets EL Service services.

    A photographed plan names a store the crew already knows; matching that name
    against this catalog (see services.store_catalog) yields the authoritative
    address, coordinate, and default tasks — so a cheap reader can do the
    extraction and known stores never need geocoding.
    """

    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Alternate spellings the plan might use (e.g. "Aldi Leipzig Zentrum").
    aliases: Mapped[list[str] | None] = mapped_column(JSONB)
    street: Mapped[str | None] = mapped_column(String)
    postal_code: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    geom: Mapped[WKBElement | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False)
    )
    # Provenance of the address/coordinate above. The stop keeps whatever the
    # plan printed as claimed_*; this row is what routing and navigation trust.
    address_provenance: Mapped[AddressProvenance] = mapped_column(
        SAEnum(
            AddressProvenance,
            name="address_provenance",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=AddressProvenance.printed,
        server_default=AddressProvenance.printed.value,
    )
    geom_provenance: Mapped[GeomProvenance | None] = mapped_column(
        SAEnum(
            GeomProvenance,
            name="geom_provenance",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str | None] = mapped_column(String)
    # Single weekday opening/closing pair (the tour runs Mon–Fri and German
    # retail hours are near-uniform across weekdays). Hours are a property of
    # the shop — stops read them through Stop.effective_hours.
    opening_time: Mapped[time | None] = mapped_column(Time)
    # closing_time drives the "done before it closes" feasibility check.
    closing_time: Mapped[time | None] = mapped_column(Time)
    # Null = hours never captured for this store.
    hours_source: Mapped[HoursSource | None] = mapped_column(
        SAEnum(
            HoursSource,
            name="hours_source",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    default_tasks: Mapped[list[str] | None] = mapped_column(JSONB)
    default_service_minutes: Mapped[int | None] = mapped_column(Integer)
    # Learned from completion history (P4, services.service_times): the median
    # observed service duration, set only once enough samples exist. Preferred
    # over default_service_minutes wherever a service estimate is needed.
    learned_service_minutes: Mapped[int | None] = mapped_column(Integer)
    # How many usable observations the last recompute found (kept even below
    # the learning threshold, so the office sees data accruing).
    service_time_samples: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    service_times_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # Crowdsourced store attributes (P3+): null means "not captured yet", so the
    # mobile app knows to prompt the crew. Set via PATCH /stores/{id}/attributes.
    size: Mapped[StoreSize | None] = mapped_column(
        SAEnum(
            StoreSize,
            name="store_size",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    in_mall: Mapped[bool | None] = mapped_column(Boolean)
    has_parking: Mapped[bool | None] = mapped_column(Boolean)
    attributes_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    attributes_updated_by: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # The store's service ledger (P4): every performed service with its team,
    # tasks, and derived duration. All time aggregates the office sees —
    # totals, per-profile medians, the learned estimate — come from these.
    service_records: Mapped[list["ServiceRecord"]] = relationship(  # noqa: F821
        back_populates="store", cascade="all, delete-orphan"
    )

    @property
    def attributes_complete(self) -> bool:
        """All crowdsourced attributes captured — nothing left to prompt for."""
        return (
            self.size is not None
            and self.in_mall is not None
            and self.has_parking is not None
        )
