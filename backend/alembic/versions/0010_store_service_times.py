"""store_service_times: learned durations per (store, service profile)

Revision ID: 0010_store_service_times
Revises: 0009_push_tokens
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_store_service_times"
down_revision: str | None = "0009_push_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "store_service_times",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "store_id",
            sa.Integer(),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_signature", sa.String(), nullable=False),
        sa.Column("tasks_label", sa.String(), nullable=True),
        sa.Column("learned_minutes", sa.Integer(), nullable=True),
        sa.Column("samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "store_id", "task_signature", name="uq_store_service_profile"
        ),
    )
    op.create_index(
        "ix_store_service_times_store_id", "store_service_times", ["store_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_store_service_times_store_id", table_name="store_service_times")
    op.drop_table("store_service_times")
