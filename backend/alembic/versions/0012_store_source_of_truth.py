"""store is the source of truth; the stop keeps the plan's claim as audit

Revision ID: 0012_store_source_of_truth
Revises: 0011_service_records
Create Date: 2026-07-17

- stores gain opening/closing hours (moved from stops — hours are a property
  of the shop, not of a plan row), plus address/geom provenance and
  verification metadata. Existing stop hours migrate across keyed by
  store_id, last non-null wins (highest stop id).
- stops keep what the paper said, renamed claimed_* so the intent is
  unmissable: claimed_street/postal_code/city/order_no and claimed_geom
  ("what the printed address geocoded to" — diagnostic, never authoritative).
  address_matches_store records whether the claim agreed with the store's
  verified address (set at commit; null = not checked yet).

No claimed_* data is deleted: it is the audit trail that shows the office
when their printed plan was wrong.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_store_source_of_truth"
down_revision: str | None = "0011_service_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Reuses the existing 'hours_source' enum type (created in 0002); it simply
# moves from stops to stores.
hours_source = postgresql.ENUM(
    "osm", "manual", "default", name="hours_source", create_type=False
)
address_provenance = postgresql.ENUM(
    "printed", "geocoded", "verified", "field_confirmed", name="address_provenance"
)
geom_provenance = postgresql.ENUM(
    "geocoded", "verified", "field_confirmed", name="geom_provenance"
)


def upgrade() -> None:
    bind = op.get_bind()
    address_provenance.create(bind, checkfirst=True)
    geom_provenance.create(bind, checkfirst=True)

    # --- stores: hours + provenance + verification ---------------------------
    op.add_column("stores", sa.Column("opening_time", sa.Time(), nullable=True))
    op.add_column("stores", sa.Column("closing_time", sa.Time(), nullable=True))
    # Nullable on the store: null = hours never captured (stops used a
    # non-null 'default' sentinel instead).
    op.add_column("stores", sa.Column("hours_source", hours_source, nullable=True))
    op.add_column(
        "stores",
        sa.Column(
            "address_provenance",
            address_provenance,
            nullable=False,
            server_default="printed",
        ),
    )
    op.add_column(
        "stores", sa.Column("geom_provenance", geom_provenance, nullable=True)
    )
    op.add_column(
        "stores", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("stores", sa.Column("verified_by", sa.String(), nullable=True))

    # Move hours across: per field, the latest stop (highest id) linked to the
    # store that has a value wins. hours_source comes from the latest stop
    # that actually knew its hours (source != 'default').
    for column in ("opening_time", "closing_time"):
        op.execute(f"""
            UPDATE stores s SET {column} = x.{column}
            FROM (
                SELECT DISTINCT ON (store_id) store_id, {column}
                FROM stops
                WHERE store_id IS NOT NULL AND {column} IS NOT NULL
                ORDER BY store_id, id DESC
            ) x
            WHERE s.id = x.store_id
            """)
    op.execute("""
        UPDATE stores s SET hours_source = x.hours_source
        FROM (
            SELECT DISTINCT ON (store_id) store_id, hours_source
            FROM stops
            WHERE store_id IS NOT NULL AND hours_source <> 'default'
            ORDER BY store_id, id DESC
        ) x
        WHERE s.id = x.store_id
        """)

    # --- stops: the printed claim, named as such -----------------------------
    op.alter_column("stops", "street", new_column_name="claimed_street")
    op.alter_column("stops", "postal_code", new_column_name="claimed_postal_code")
    op.alter_column("stops", "city", new_column_name="claimed_city")
    op.alter_column("stops", "order_no", new_column_name="claimed_order_no")
    op.alter_column("stops", "geom", new_column_name="claimed_geom")
    op.add_column(
        "stops", sa.Column("address_matches_store", sa.Boolean(), nullable=True)
    )

    op.drop_column("stops", "hours_source")
    op.drop_column("stops", "closing_time")
    op.drop_column("stops", "opening_time")


def downgrade() -> None:
    op.add_column("stops", sa.Column("opening_time", sa.Time(), nullable=True))
    op.add_column("stops", sa.Column("closing_time", sa.Time(), nullable=True))
    op.add_column(
        "stops",
        sa.Column(
            "hours_source", hours_source, server_default="default", nullable=False
        ),
    )
    # Restore each stop's hours from its store (the per-stop originals are
    # gone; the store's values are the surviving truth).
    op.execute("""
        UPDATE stops st
        SET opening_time = s.opening_time,
            closing_time = s.closing_time,
            hours_source = COALESCE(s.hours_source, 'default')
        FROM stores s
        WHERE st.store_id = s.id
        """)

    op.drop_column("stops", "address_matches_store")
    op.alter_column("stops", "claimed_geom", new_column_name="geom")
    op.alter_column("stops", "claimed_order_no", new_column_name="order_no")
    op.alter_column("stops", "claimed_city", new_column_name="city")
    op.alter_column("stops", "claimed_postal_code", new_column_name="postal_code")
    op.alter_column("stops", "claimed_street", new_column_name="street")

    op.drop_column("stores", "verified_by")
    op.drop_column("stores", "verified_at")
    op.drop_column("stores", "geom_provenance")
    op.drop_column("stores", "address_provenance")
    op.drop_column("stores", "hours_source")
    op.drop_column("stores", "closing_time")
    op.drop_column("stores", "opening_time")
    geom_provenance.drop(op.get_bind(), checkfirst=True)
    address_provenance.drop(op.get_bind(), checkfirst=True)
