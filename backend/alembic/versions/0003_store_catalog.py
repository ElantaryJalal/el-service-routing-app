"""store catalog + stops.store_id

Revision ID: 0003_store_catalog
Revises: 0002_stop_hours
Create Date: 2026-07-02

Adds the `stores` catalog (canonical name/address/coordinate/default tasks for
the known supermarkets) and a nullable `stops.store_id` linking a stop to the
catalog store it was matched to.
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_store_catalog"
down_revision: str | None = "0002_stop_hours"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _point() -> geoalchemy2.Geometry:
    return geoalchemy2.Geometry(geometry_type="POINT", srid=4326, spatial_index=False)


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("aliases", postgresql.JSONB, nullable=True),
        sa.Column("street", sa.String, nullable=True),
        sa.Column("postal_code", sa.String, nullable=True),
        sa.Column("city", sa.String, nullable=True),
        sa.Column("geom", _point(), nullable=True),
        sa.Column("default_tasks", postgresql.JSONB, nullable=True),
        sa.Column("default_service_minutes", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_stores_geom", "stores", ["geom"], postgresql_using="gist")

    op.add_column(
        "stops",
        sa.Column(
            "store_id",
            sa.Integer,
            sa.ForeignKey("stores.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_stops_store_id", "stops", ["store_id"])


def downgrade() -> None:
    op.drop_index("ix_stops_store_id", table_name="stops")
    op.drop_column("stops", "store_id")
    op.drop_index("ix_stores_geom", table_name="stores")
    op.drop_table("stores")
