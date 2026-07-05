from datetime import datetime

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
