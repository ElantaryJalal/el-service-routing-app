"""demo stores: is_demo flag on the catalog + a 'seeded' hours source

The showcase seed (scripts.seed_demo_showcase) needs catalog stores it can
fully populate — size/parking/mall, opening hours, service defaults — WITHOUT
touching the real, verified catalog a production tour would match against. So
stores gain the same is_demo marker every other seedable table already has:
demo stores are excluded from name/order-no matching (never attach to a real
tour), hidden from the office store list unless demo data is toggled on, and
removed in one action. A 'seeded' hours_source value labels their opening
hours as showcase values rather than something checked against OSM.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_demo_stores"
down_revision: str | None = "0014_is_demo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stores",
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # New enum value must be committed before it can be used, so add it in its
    # own transaction (Alembic runs the migration inside one otherwise).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE hours_source ADD VALUE IF NOT EXISTS 'seeded'")


def downgrade() -> None:
    # Postgres cannot drop an enum value; the unused 'seeded' label is harmless.
    op.drop_column("stores", "is_demo")
