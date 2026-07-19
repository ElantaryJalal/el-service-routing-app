"""separate demo/test rows from real data (is_demo flag + backfill)

Revision ID: 0014_is_demo
Revises: 0013_address_review
Create Date: 2026-07-18

Management views must never mix simulated content with real operations. Every
seedable record gets an is_demo boolean (default false); office dashboard
queries exclude demo rows unless explicitly asked. The backfill identifies
existing demo rows by their known markers: the demo/e2e users
(…@e2e.elservice.de, "Demo Mitarbeiter"), the seed scripts' customer/vehicle
tags, "(Demo)" note markers, and demo client uuids — plus everything hanging
off a demo tour.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_is_demo"
down_revision: str | None = "0013_address_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("tours", "stops", "visit_feedback", "service_records")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "is_demo", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )

    # Demo tours: the seed script's customer tag, the demo-history clone tag,
    # or an assignment to a demo/e2e worker (the live-demo driver).
    op.execute("""
        UPDATE tours SET is_demo = true
        WHERE customer LIKE 'DEMO %'
           OR vehicle = 'demo-history-kw27'
           OR assigned_user_id IN (
                SELECT id FROM users
                WHERE email LIKE '%@e2e.elservice.de' OR name = 'Demo Mitarbeiter'
           )
        """)
    op.execute(
        "UPDATE stops SET is_demo = true"
        " WHERE tour_id IN (SELECT id FROM tours WHERE is_demo)"
    )
    op.execute("""
        UPDATE visit_feedback SET is_demo = true
        WHERE employee = 'Demo Mitarbeiter'
           OR note LIKE '%(Demo)%'
           OR client_uuid LIKE 'demo-%'
           OR tour_id IN (SELECT id FROM tours WHERE is_demo)
        """)
    op.execute("""
        UPDATE service_records SET is_demo = true
        WHERE team = 'Demo Mitarbeiter'
           OR tour_id IN (SELECT id FROM tours WHERE is_demo)
           OR stop_id IN (SELECT id FROM stops WHERE is_demo)
        """)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_column(table, "is_demo")
