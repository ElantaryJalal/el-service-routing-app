"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-01

"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _point() -> geoalchemy2.Geometry:
    # spatial_index=False: GiST indexes are created explicitly below so the
    # migration owns them with predictable names.
    return geoalchemy2.Geometry(geometry_type="POINT", srid=4326, spatial_index=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "hotels",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("address", sa.String, nullable=True),
        sa.Column("geom", _point(), nullable=True),
    )

    op.create_table(
        "employees",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
    )

    op.create_table(
        "tours",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("customer", sa.String, nullable=False),
        sa.Column("calendar_week", sa.Integer, nullable=False),
        sa.Column("date_from", sa.Date, nullable=False),
        sa.Column("date_to", sa.Date, nullable=False),
        sa.Column("team_lead", sa.String, nullable=True),
        sa.Column("employee", sa.String, nullable=True),
        sa.Column("vehicle", sa.String, nullable=True),
        sa.Column(
            "hotel_id",
            sa.Integer,
            sa.ForeignKey("hotels.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String, nullable=False, server_default="draft"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "stops",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "tour_id",
            sa.Integer,
            sa.ForeignKey("tours.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_index", sa.Integer, nullable=False),
        sa.Column("date", sa.Date, nullable=True),
        sa.Column("weekday", sa.String, nullable=True),
        sa.Column("customer", sa.String, nullable=True),
        sa.Column("order_no", sa.String, nullable=True),
        sa.Column("street", sa.String, nullable=True),
        sa.Column("postal_code", sa.String, nullable=True),
        sa.Column("city", sa.String, nullable=True),
        sa.Column("remarks_raw", sa.Text, nullable=True),
        sa.Column("handwritten_notes", sa.Text, nullable=True),
        sa.Column("status_hint", sa.String, nullable=False, server_default="unknown"),
        sa.Column("service_minutes", sa.Integer, nullable=True),
        sa.Column("assigned_day", sa.Date, nullable=True),
        sa.Column("sequence", sa.Integer, nullable=True),
        sa.Column("eta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("geom", _point(), nullable=True),
        sa.Column("confidence", postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="unconfirmed"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_stops_tour_id", "stops", ["tour_id"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "stop_id",
            sa.Integer,
            sa.ForeignKey("stops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_type", sa.String, nullable=False),
        sa.Column("raw_label", sa.String, nullable=True),
    )
    op.create_index("ix_tasks_stop_id", "tasks", ["stop_id"])

    op.create_table(
        "geocode_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("normalized_address", sa.String, nullable=False, unique=True),
        sa.Column("geom", _point(), nullable=False),
        sa.Column("provider", sa.String, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Spatial (GiST) indexes on geometry columns.
    op.create_index("ix_hotels_geom", "hotels", ["geom"], postgresql_using="gist")
    op.create_index("ix_stops_geom", "stops", ["geom"], postgresql_using="gist")
    op.create_index(
        "ix_geocode_cache_geom",
        "geocode_cache",
        ["geom"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("ix_geocode_cache_geom", table_name="geocode_cache")
    op.drop_index("ix_stops_geom", table_name="stops")
    op.drop_index("ix_hotels_geom", table_name="hotels")
    op.drop_table("geocode_cache")
    op.drop_index("ix_tasks_stop_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_stops_tour_id", table_name="stops")
    op.drop_table("stops")
    op.drop_table("tours")
    op.drop_table("employees")
    op.drop_table("hotels")
    # The postgis extension is left installed intentionally.
