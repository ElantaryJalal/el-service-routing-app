"""add opening/closing hours to stops

Revision ID: 0002_stop_hours
Revises: 0001_initial
Create Date: 2026-07-01

Note: service_minutes already exists (added in 0001_initial), so this migration
only adds opening_time, closing_time, and the hours_source enum.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_stop_hours"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

hours_source = postgresql.ENUM("osm", "manual", "default", name="hours_source")


def upgrade() -> None:
    hours_source.create(op.get_bind(), checkfirst=True)
    op.add_column("stops", sa.Column("opening_time", sa.Time(), nullable=True))
    op.add_column("stops", sa.Column("closing_time", sa.Time(), nullable=True))
    op.add_column(
        "stops",
        sa.Column(
            "hours_source",
            hours_source,
            server_default="default",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("stops", "hours_source")
    op.drop_column("stops", "closing_time")
    op.drop_column("stops", "opening_time")
    hours_source.drop(op.get_bind(), checkfirst=True)
