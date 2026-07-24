"""Add user-owned creative projects.

Revision ID: 20260724_0005
Revises: 20260724_0004
Create Date: 2026-07-24 00:00:03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0005"
down_revision: str | Sequence[str] | None = "20260724_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("user_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("audience", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_projects_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_index(
        "ix_projects_user_id_updated_at",
        "projects",
        ["user_id", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_projects_user_id_updated_at", table_name="projects")
    op.drop_table("projects")
