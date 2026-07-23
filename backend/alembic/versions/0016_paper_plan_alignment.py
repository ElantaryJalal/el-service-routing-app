"""align the model with the paper Tourenplan

Undo what the app dropped or broke relative to the printed plan:

- stops.claimed_order_no -> stops.order_no. The Auftrag/VST number is the
  office's first-class job reference (and their invoicing key), not an
  unreliable "claim" to validate against the store — so it loses the
  ``claimed_`` prefix and its diagnostic framing.
- tours.team_no: the paper's "Team-Nr." was being buried inside the free-text
  employee field; it gets its own column alongside team_lead/employee/vehicle.
- Drop the hotels table and tours.hotel_id. The route models overnight hotels
  as free vehicle starts (optimiser), never as catalog rows — the table has
  always been empty and was dead weight.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from geoalchemy2 import Geometry

from alembic import op

revision: str = "0016_paper_plan_alignment"
down_revision: str | None = "0015_demo_stores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("stops", "claimed_order_no", new_column_name="order_no")
    op.add_column("tours", sa.Column("team_no", sa.String(), nullable=True))
    op.drop_constraint("tours_hotel_id_fkey", "tours", type_="foreignkey")
    op.drop_column("tours", "hotel_id")
    op.drop_table("hotels")


def downgrade() -> None:
    op.create_table(
        "hotels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column(
            "geom",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
    )
    op.add_column("tours", sa.Column("hotel_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "tours_hotel_id_fkey",
        "tours",
        "hotels",
        ["hotel_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_column("tours", "team_no")
    op.alter_column("stops", "order_no", new_column_name="claimed_order_no")
