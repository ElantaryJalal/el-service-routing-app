"""service_records: the service ledger replaces the aggregate-only table

One row per service performed at a store — stop, tour, responsible team,
tasks, derived duration. store_service_times (an aggregate keyed by task
signature) is dropped: every learned estimate is now computed from the
ledger, so the office can always drill from a number down to the services
behind it.

Revision ID: 0011_service_records
Revises: 0010_store_service_times
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_service_records"
down_revision: str | None = "0010_store_service_times"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "stop_id",
            sa.Integer(),
            sa.ForeignKey("stops.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "store_id",
            sa.Integer(),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tour_id",
            sa.Integer(),
            sa.ForeignKey("tours.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("team", sa.String(), nullable=True),
        sa.Column("serviced_on", sa.Date(), nullable=True),
        sa.Column("task_signature", sa.String(), nullable=False, server_default=""),
        sa.Column("tasks_label", sa.String(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_service_records_store_id", "service_records", ["store_id"])

    op.drop_index("ix_store_service_times_store_id", table_name="store_service_times")
    op.drop_table("store_service_times")


def downgrade() -> None:
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
    op.drop_index("ix_service_records_store_id", table_name="service_records")
    op.drop_table("service_records")
