"""date mode, completion capture, store attributes, visit feedback

Revision ID: 0004_completion_feedback
Revises: 0003_store_catalog
Create Date: 2026-07-12

Schema only (no feature logic): tours.date_mode, crowdsourced store attributes
(size/in_mall/has_parking + updated audit pair), stops.completed_at as the
source of truth for "done", and the append-only visit_feedback table with a
unique client_uuid as the offline-sync idempotency key.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_completion_feedback"
down_revision: str | None = "0003_store_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

date_mode = postgresql.ENUM("fixed", "optimized", name="date_mode")
store_size = postgresql.ENUM("small", "medium", "large", name="store_size")


def upgrade() -> None:
    date_mode.create(op.get_bind(), checkfirst=True)
    store_size.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tours",
        sa.Column("date_mode", date_mode, server_default="fixed", nullable=False),
    )

    op.add_column("stores", sa.Column("size", store_size, nullable=True))
    op.add_column("stores", sa.Column("in_mall", sa.Boolean(), nullable=True))
    op.add_column("stores", sa.Column("has_parking", sa.Boolean(), nullable=True))
    op.add_column(
        "stores",
        sa.Column("attributes_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stores", sa.Column("attributes_updated_by", sa.String(), nullable=True)
    )

    op.add_column(
        "stops", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "visit_feedback",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "store_id",
            sa.Integer,
            sa.ForeignKey("stores.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "tour_id",
            sa.Integer,
            sa.ForeignKey("tours.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "stop_id",
            sa.Integer,
            sa.ForeignKey("stops.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("employee", sa.String, nullable=True),
        sa.Column(
            "tags",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("photo_path", sa.String, nullable=True),
        sa.Column("client_uuid", sa.String, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("client_uuid", name="uq_visit_feedback_client_uuid"),
    )
    op.create_index("ix_visit_feedback_store_id", "visit_feedback", ["store_id"])
    op.create_index("ix_visit_feedback_tour_id", "visit_feedback", ["tour_id"])
    op.create_index("ix_visit_feedback_stop_id", "visit_feedback", ["stop_id"])


def downgrade() -> None:
    op.drop_index("ix_visit_feedback_stop_id", table_name="visit_feedback")
    op.drop_index("ix_visit_feedback_tour_id", table_name="visit_feedback")
    op.drop_index("ix_visit_feedback_store_id", table_name="visit_feedback")
    op.drop_table("visit_feedback")

    op.drop_column("stops", "completed_at")

    op.drop_column("stores", "attributes_updated_by")
    op.drop_column("stores", "attributes_updated_at")
    op.drop_column("stores", "has_parking")
    op.drop_column("stores", "in_mall")
    op.drop_column("stores", "size")

    op.drop_column("tours", "date_mode")

    store_size.drop(op.get_bind(), checkfirst=True)
    date_mode.drop(op.get_bind(), checkfirst=True)
