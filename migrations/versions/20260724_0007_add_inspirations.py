"""Add user-owned inspirations and project associations.

Revision ID: 20260724_0007
Revises: 20260724_0006
Create Date: 2026-07-24 00:00:05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0007"
down_revision: str | Sequence[str] | None = "20260724_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inspirations",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("user_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="inbox",
            nullable=False,
        ),
        sa.Column(
            "source_type",
            sa.String(length=16),
            server_default="manual",
            nullable=False,
        ),
        sa.Column(
            "source_conversation_id",
            sa.Uuid(native_uuid=False),
            nullable=True,
        ),
        sa.Column(
            "source_message_id",
            sa.Uuid(native_uuid=False),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('inbox', 'developing', 'converted', 'archived')",
            name=op.f("ck_inspirations_status_valid"),
        ),
        sa.CheckConstraint(
            "source_type IN ('manual', 'agent', 'voice')",
            name=op.f("ck_inspirations_source_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["agent_conversations.id"],
            name=op.f("fk_inspirations_source_conversation_id_agent_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["agent_messages.id"],
            name=op.f("fk_inspirations_source_message_id_agent_messages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_inspirations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inspirations")),
    )
    op.create_index(
        "ix_inspirations_user_id_updated_at",
        "inspirations",
        ["user_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_inspirations_user_id_status_updated_at",
        "inspirations",
        ["user_id", "status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_inspirations_source_conversation_id",
        "inspirations",
        ["source_conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_inspirations_source_message_id",
        "inspirations",
        ["source_message_id"],
        unique=False,
    )

    op.create_table(
        "inspiration_projects",
        sa.Column(
            "inspiration_id",
            sa.Uuid(native_uuid=False),
            nullable=False,
        ),
        sa.Column("project_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.ForeignKeyConstraint(
            ["inspiration_id"],
            ["inspirations.id"],
            name=op.f("fk_inspiration_projects_inspiration_id_inspirations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_inspiration_projects_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "inspiration_id",
            "project_id",
            name=op.f("pk_inspiration_projects"),
        ),
    )
    op.create_index(
        "ix_inspiration_projects_project_id_inspiration_id",
        "inspiration_projects",
        ["project_id", "inspiration_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inspiration_projects_project_id_inspiration_id",
        table_name="inspiration_projects",
    )
    op.drop_table("inspiration_projects")
    op.drop_index(
        "ix_inspirations_source_message_id",
        table_name="inspirations",
    )
    op.drop_index(
        "ix_inspirations_source_conversation_id",
        table_name="inspirations",
    )
    op.drop_index(
        "ix_inspirations_user_id_status_updated_at",
        table_name="inspirations",
    )
    op.drop_index(
        "ix_inspirations_user_id_updated_at",
        table_name="inspirations",
    )
    op.drop_table("inspirations")
