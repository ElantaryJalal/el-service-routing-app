import enum
from datetime import datetime

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class StoreSize(enum.StrEnum):
    small = "small"
    medium = "medium"
    large = "large"


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

    @property
    def attributes_complete(self) -> bool:
        """All crowdsourced attributes captured — nothing left to prompt for."""
        return (
            self.size is not None
            and self.in_mall is not None
            and self.has_parking is not None
        )
