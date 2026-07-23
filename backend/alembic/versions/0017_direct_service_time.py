"""direct service-time measurement

Add the pieces for measuring service time directly from the worker's own
start/done stamps, keeping the derived (drive-subtracted) method as a fallback:

- stops.started_at (nullable) + stops.start_source enum(auto|manual|none),
  default 'none' — set via POST /stops/{id}/start.
- service_records.measurement_method enum(direct|derived), default 'derived'
  so every existing (derived) row keeps its meaning.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_direct_service_time"
down_revision: str | None = "0016_paper_plan_alignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False: the types are created/dropped explicitly below.
start_source = postgresql.ENUM(
    "auto", "manual", "none", name="start_source", create_type=False
)
measurement_method = postgresql.ENUM(
    "direct", "derived", name="measurement_method", create_type=False
)


def upgrade() -> None:
    start_source.create(op.get_bind(), checkfirst=True)
    measurement_method.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "stops",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stops",
        sa.Column(
            "start_source",
            start_source,
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "service_records",
        sa.Column(
            "measurement_method",
            measurement_method,
            nullable=False,
            server_default="derived",
        ),
    )


def downgrade() -> None:
    op.drop_column("service_records", "measurement_method")
    op.drop_column("stops", "start_source")
    op.drop_column("stops", "started_at")
    measurement_method.drop(op.get_bind(), checkfirst=True)
    start_source.drop(op.get_bind(), checkfirst=True)
