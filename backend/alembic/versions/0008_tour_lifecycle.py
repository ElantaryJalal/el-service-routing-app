"""tours.status becomes the tour_status lifecycle enum

Revision ID: 0008_tour_lifecycle
Revises: 0007_users_auth
Create Date: 2026-07-14

Converts the free-string tours.status ('draft' | 'confirmed') to the enum
draft -> planned -> assigned -> in_progress -> done. Existing 'confirmed'
tours become 'planned', then are promoted where the data already says more:
'assigned' if a user is assigned, 'in_progress' if any stop is completed,
'done' if every stop is. stops.status is a different concept (optimiser
input) and stays a string.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_tour_lifecycle"
down_revision: str | None = "0007_users_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False: created/dropped explicitly below.
tour_status = postgresql.ENUM(
    "draft",
    "planned",
    "assigned",
    "in_progress",
    "done",
    name="tour_status",
    create_type=False,
)


def upgrade() -> None:
    tour_status.create(op.get_bind(), checkfirst=True)

    op.execute("UPDATE tours SET status = 'planned' WHERE status = 'confirmed'")
    # Safety net for any other legacy value.
    op.execute(
        "UPDATE tours SET status = 'draft' WHERE status NOT IN "
        "('draft', 'planned', 'assigned', 'in_progress', 'done')"
    )
    # Promote tours whose data already implies a later lifecycle stage.
    op.execute(
        "UPDATE tours SET status = 'assigned' "
        "WHERE status = 'planned' AND assigned_user_id IS NOT NULL"
    )
    op.execute(
        "UPDATE tours SET status = 'in_progress' WHERE status = 'assigned' "
        "AND EXISTS (SELECT 1 FROM stops WHERE stops.tour_id = tours.id "
        "AND stops.completed_at IS NOT NULL)"
    )
    op.execute(
        "UPDATE tours SET status = 'done' WHERE status = 'in_progress' "
        "AND NOT EXISTS (SELECT 1 FROM stops WHERE stops.tour_id = tours.id "
        "AND stops.completed_at IS NULL)"
    )

    # The old varchar default must go before the type change.
    op.execute("ALTER TABLE tours ALTER COLUMN status DROP DEFAULT")
    op.alter_column(
        "tours",
        "status",
        type_=tour_status,
        postgresql_using="status::tour_status",
        existing_nullable=False,
    )
    op.execute("ALTER TABLE tours ALTER COLUMN status SET DEFAULT 'draft'")


def downgrade() -> None:
    op.execute("ALTER TABLE tours ALTER COLUMN status DROP DEFAULT")
    op.alter_column(
        "tours",
        "status",
        type_=sa.String(),
        postgresql_using="status::text",
        existing_nullable=False,
    )
    op.execute("ALTER TABLE tours ALTER COLUMN status SET DEFAULT 'draft'")
    op.execute(
        "UPDATE tours SET status = 'confirmed' "
        "WHERE status IN ('planned', 'assigned', 'in_progress', 'done')"
    )
    tour_status.drop(op.get_bind(), checkfirst=True)
