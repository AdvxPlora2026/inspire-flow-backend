"""Add encrypted transcription analysis metadata.

Revision ID: 20260724_0004
Revises: 20260724_0003
Create Date: 2026-07-24 00:00:02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0004"
down_revision: str | Sequence[str] | None = "20260724_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transcription_jobs",
        sa.Column("analysis_ciphertext", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transcription_jobs", "analysis_ciphertext")
