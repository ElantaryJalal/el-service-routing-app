"""per-stop unassigned reason

Revision ID: 0006_unassigned_reason
Revises: 0005_learned_service_times
Create Date: 2026-07-13

Why a stop is off the plan (optimiser verdict or a manual removal), persisted
so GET /tours/{id}/plan can rebuild the schedule — reasons included — without
re-running the solver. Null whenever the stop is assigned to a day.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_unassigned_reason"
down_revision: str | None = "0005_learned_service_times"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stops", sa.Column("unassigned_reason", sa.String(length=120), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("stops", "unassigned_reason")
