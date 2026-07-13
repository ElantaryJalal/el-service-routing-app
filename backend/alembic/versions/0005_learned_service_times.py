"""learned per-store service times

Revision ID: 0005_learned_service_times
Revises: 0004_completion_feedback
Create Date: 2026-07-13

Schema only: the three columns POST /stores/service-times/recompute maintains —
the learned median service duration, the observation count behind it, and when
the learner last ran.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_learned_service_times"
down_revision: str | None = "0004_completion_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stores", sa.Column("learned_service_minutes", sa.Integer(), nullable=True)
    )
    op.add_column(
        "stores",
        sa.Column(
            "service_time_samples",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "stores",
        sa.Column(
            "service_times_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("stores", "service_times_updated_at")
    op.drop_column("stores", "service_time_samples")
    op.drop_column("stores", "learned_service_minutes")
