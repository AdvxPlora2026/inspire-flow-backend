"""Add asynchronous transcription jobs.

Revision ID: 20260724_0003
Revises: 20260724_0002
Create Date: 2026-07-24 00:00:01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0003"
down_revision: str | Sequence[str] | None = "20260724_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transcription_jobs",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("user_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column(
            "use_itn",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("transcript_ciphertext", sa.Text(), nullable=True),
        sa.Column("detected_language", sa.String(length=16), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_transcription_jobs_status_valid"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_transcription_jobs_attempt_count_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_transcription_jobs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transcription_jobs")),
    )
    op.create_index(
        "ix_transcription_jobs_user_id_created_at",
        "transcription_jobs",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transcription_jobs_user_id_created_at",
        table_name="transcription_jobs",
    )
    op.drop_table("transcription_jobs")
