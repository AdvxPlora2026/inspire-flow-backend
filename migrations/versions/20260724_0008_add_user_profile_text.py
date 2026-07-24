"""Add Agent-managed user profile text.

Revision ID: 20260724_0008
Revises: 20260724_0007
Create Date: 2026-07-24 00:00:06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0008"
down_revision: str | Sequence[str] | None = "20260724_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("profile_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "profile_text")
