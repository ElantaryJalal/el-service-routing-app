"""users table, role enum, tours.assigned_user_id; drop employees

Revision ID: 0007_users_auth
Revises: 0006_unassigned_reason
Create Date: 2026-07-14

Auth foundation: the users table (bcrypt password_hash, user_role enum) and a
nullable tours.assigned_user_id FK. A field worker is now a User with
role='worker', superseding the never-queried, empty employees placeholder
table, which is dropped. The free-text tours.employee column stays as plan
provenance (what the photographed plan said); linking names to real users is
done by scripts/backfill_tour_users.py, not here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_users_auth"
down_revision: str | None = "0006_unassigned_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False: the type is created/dropped explicitly below; without it
# create_table would emit a second CREATE TYPE and collide.
user_role = postgresql.ENUM(
    "worker", "dispatcher", "manager", "admin", name="user_role", create_type=False
)


def upgrade() -> None:
    user_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("password_hash", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.add_column(
        "tours",
        sa.Column(
            "assigned_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.drop_table("employees")


def downgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
    )

    op.drop_column("tours", "assigned_user_id")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    user_role.drop(op.get_bind(), checkfirst=True)
