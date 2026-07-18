"""dispatcher resolution stamp for plan-vs-store address mismatches

Revision ID: 0013_address_review
Revises: 0012_store_source_of_truth
Create Date: 2026-07-18

A mismatch (address_matches_store=false) is recomputed on every commit, so a
dispatcher's "the store is correct" decision needs its own durable stamp —
otherwise the review row would reappear after each re-commit. The claim itself
is never touched: it stays the audit trail of what the paper said.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_address_review"
down_revision: str | None = "0012_store_source_of_truth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stops",
        sa.Column("address_review_resolved_at", sa.DateTime(timezone=True)),
    )
    op.add_column("stops", sa.Column("address_review_resolved_by", sa.String()))


def downgrade() -> None:
    op.drop_column("stops", "address_review_resolved_by")
    op.drop_column("stops", "address_review_resolved_at")
