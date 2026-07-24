"""Add nonce to chain transactions for inclusion-based confirmation.

Revision ID: 20260724_0011
Revises: 20260724_0010
Create Date: 2026-07-24 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0011"
down_revision: str | Sequence[str] | None = "20260724_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chain_transactions",
        sa.Column("nonce", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chain_transactions", "nonce")
