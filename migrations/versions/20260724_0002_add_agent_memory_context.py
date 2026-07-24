"""Add Agent conversations, memories and creator profiles.

Revision ID: 20260724_0002
Revises: 20260723_0001
Create Date: 2026-07-24 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0002"
down_revision: str | Sequence[str] | None = "20260723_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("preferred_language", sa.String(length=35), nullable=True),
        sa.Column("creator_identity", sa.String(length=100), nullable=True),
        sa.Column(
            "content_focus",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("collaboration_preferences", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_profiles")),
    )
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("user_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("summary_ciphertext", sa.Text(), nullable=True),
        sa.Column(
            "summary_through_sequence",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("summary_updated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "next_sequence",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("active_run_id", sa.Uuid(native_uuid=False), nullable=True),
        sa.Column("active_run_started_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "summary_through_sequence >= 0",
            name=op.f("ck_agent_conversations_summary_sequence_nonnegative"),
        ),
        sa.CheckConstraint(
            "next_sequence > 0",
            name=op.f("ck_agent_conversations_next_sequence_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_conversations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_conversations")),
    )
    op.create_index(
        "ix_agent_conversations_user_id_updated_at",
        "agent_conversations",
        ["user_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_conversations_user_id_archived_at",
        "agent_conversations",
        ["user_id", "archived_at"],
        unique=False,
    )

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("conversation_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("turn_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("payload_ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "sequence > 0",
            name=op.f("ck_agent_messages_sequence_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent_conversations.id"],
            name=op.f("fk_agent_messages_conversation_id_agent_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_messages")),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_agent_messages_conversation_id_sequence",
        ),
    )
    op.create_index(
        "ix_agent_messages_conversation_id_sequence",
        "agent_messages",
        ["conversation_id", "sequence"],
        unique=False,
    )
    op.create_index(
        "ix_agent_messages_conversation_id_turn_id",
        "agent_messages",
        ["conversation_id", "turn_id"],
        unique=False,
    )

    op.create_table(
        "user_memories",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("user_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("content_ciphertext", sa.Text(), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column(
            "is_sensitive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "user_edited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("source_conversation_id", sa.Uuid(native_uuid=False), nullable=True),
        sa.Column("source_message_id", sa.Uuid(native_uuid=False), nullable=True),
        sa.Column("source_deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name=op.f("ck_user_memories_status_valid"),
        ),
        sa.CheckConstraint(
            "origin IN ('automatic', 'explicit', 'manual')",
            name=op.f("ck_user_memories_origin_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["agent_conversations.id"],
            name=op.f("fk_user_memories_source_conversation_id_agent_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_message_id"],
            ["agent_messages.id"],
            name=op.f("fk_user_memories_source_message_id_agent_messages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_memories_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_memories")),
        sa.UniqueConstraint(
            "user_id",
            "content_fingerprint",
            name="uq_user_memories_user_id_content_fingerprint",
        ),
    )
    op.create_index(
        "ix_user_memories_user_id_status_is_pinned_updated_at",
        "user_memories",
        ["user_id", "status", "is_pinned", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_user_memories_source_conversation_id",
        "user_memories",
        ["source_conversation_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO user_profiles (user_id, content_focus, created_at, updated_at)
            SELECT id, '[]', created_at, updated_at
            FROM users
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_memories_source_conversation_id",
        table_name="user_memories",
    )
    op.drop_index(
        "ix_user_memories_user_id_status_is_pinned_updated_at",
        table_name="user_memories",
    )
    op.drop_table("user_memories")

    op.drop_index(
        "ix_agent_messages_conversation_id_turn_id",
        table_name="agent_messages",
    )
    op.drop_index(
        "ix_agent_messages_conversation_id_sequence",
        table_name="agent_messages",
    )
    op.drop_table("agent_messages")

    op.drop_index(
        "ix_agent_conversations_user_id_archived_at",
        table_name="agent_conversations",
    )
    op.drop_index(
        "ix_agent_conversations_user_id_updated_at",
        table_name="agent_conversations",
    )
    op.drop_table("agent_conversations")
    op.drop_table("user_profiles")
