"""Add optional project icons.

Revision ID: 20260724_0006
Revises: 20260724_0005
Create Date: 2026-07-24 00:00:04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0006"
down_revision: str | Sequence[str] | None = "20260724_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("icon_url", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "icon_url")
