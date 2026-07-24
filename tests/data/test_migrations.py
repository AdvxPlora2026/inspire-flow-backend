from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

BASE_REVISION = "20260723_0001"
CONTEXT_TABLES = {
    "user_profiles",
    "agent_conversations",
    "agent_messages",
    "user_memories",
}


def make_config(database_path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def named_constraints(
    inspector: sa.Inspector,
    table_name: str,
    method_name: str,
) -> set[str]:
    constraints = getattr(inspector, method_name)(table_name)
    return {str(constraint["name"]) for constraint in constraints}


def test_migration_upgrades_backfills_and_downgrades_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    config = make_config(database_path)
    command.upgrade(config, BASE_REVISION)

    engine = sa.create_engine(f"sqlite:///{database_path}")
    existing_user_id = uuid4()
    created_at = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO users (
                    id, nickname, nickname_key, avatar_url, password_hash, created_at, updated_at
                ) VALUES (
                    :id, :nickname, :nickname_key, NULL, :password_hash, :created_at, :updated_at
                )
                """
            ),
            {
                "id": existing_user_id.hex,
                "nickname": "Existing Creator",
                "nickname_key": "existing creator",
                "password_hash": "test-only-hash",
                "created_at": created_at,
                "updated_at": created_at,
            },
        )

    command.upgrade(config, "head")

    inspector = sa.inspect(engine)
    assert {
        "alembic_version",
        "users",
        "auth_sessions",
        *CONTEXT_TABLES,
    } <= set(inspector.get_table_names())
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text("SELECT COUNT(*) FROM user_profiles WHERE user_id = :id"),
                {"id": existing_user_id.hex},
            )
            == 1
        )

    assert {column["name"] for column in inspector.get_columns("user_profiles")} == {
        "user_id",
        "bio",
        "timezone",
        "preferred_language",
        "creator_identity",
        "content_focus",
        "collaboration_preferences",
        "created_at",
        "updated_at",
    }
    assert {column["name"] for column in inspector.get_columns("agent_conversations")} == {
        "id",
        "user_id",
        "title",
        "archived_at",
        "summary_ciphertext",
        "summary_through_sequence",
        "summary_updated_at",
        "next_sequence",
        "active_run_id",
        "active_run_started_at",
        "created_at",
        "updated_at",
    }
    assert {column["name"] for column in inspector.get_columns("agent_messages")} == {
        "id",
        "conversation_id",
        "turn_id",
        "sequence",
        "item_type",
        "role",
        "payload_ciphertext",
        "created_at",
    }
    assert {column["name"] for column in inspector.get_columns("user_memories")} == {
        "id",
        "user_id",
        "category",
        "content_ciphertext",
        "content_fingerprint",
        "status",
        "origin",
        "is_sensitive",
        "is_pinned",
        "user_edited",
        "source_conversation_id",
        "source_message_id",
        "source_deleted_at",
        "created_at",
        "updated_at",
    }

    assert named_constraints(
        inspector,
        "agent_messages",
        "get_unique_constraints",
    ) == {"uq_agent_messages_conversation_id_sequence"}
    assert named_constraints(
        inspector,
        "user_memories",
        "get_unique_constraints",
    ) == {"uq_user_memories_user_id_content_fingerprint"}
    assert {
        "ck_agent_conversations_summary_sequence_nonnegative",
        "ck_agent_conversations_next_sequence_positive",
    } <= named_constraints(inspector, "agent_conversations", "get_check_constraints")
    assert {"ck_agent_messages_sequence_positive"} <= named_constraints(
        inspector,
        "agent_messages",
        "get_check_constraints",
    )
    assert {
        "ck_user_memories_status_valid",
        "ck_user_memories_origin_valid",
    } <= named_constraints(inspector, "user_memories", "get_check_constraints")

    assert {index["name"] for index in inspector.get_indexes("agent_conversations")} == {
        "ix_agent_conversations_user_id_archived_at",
        "ix_agent_conversations_user_id_updated_at",
    }
    assert {index["name"] for index in inspector.get_indexes("agent_messages")} == {
        "ix_agent_messages_conversation_id_sequence",
        "ix_agent_messages_conversation_id_turn_id",
    }
    assert {index["name"] for index in inspector.get_indexes("user_memories")} == {
        "ix_user_memories_source_conversation_id",
        "ix_user_memories_user_id_status_is_pinned_updated_at",
    }

    expected_foreign_keys = {
        ("user_profiles", "user_id"): ("users", "CASCADE"),
        ("agent_conversations", "user_id"): ("users", "CASCADE"),
        ("agent_messages", "conversation_id"): ("agent_conversations", "CASCADE"),
        ("user_memories", "user_id"): ("users", "CASCADE"),
        ("user_memories", "source_conversation_id"): ("agent_conversations", "SET NULL"),
        ("user_memories", "source_message_id"): ("agent_messages", "SET NULL"),
    }
    for (table_name, column_name), (referred_table, on_delete) in expected_foreign_keys.items():
        matching = [
            foreign_key
            for foreign_key in inspector.get_foreign_keys(table_name)
            if foreign_key["constrained_columns"] == [column_name]
        ]
        assert len(matching) == 1
        assert matching[0]["referred_table"] == referred_table
        assert matching[0]["options"]["ondelete"] == on_delete

    command.downgrade(config, BASE_REVISION)
    assert CONTEXT_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    assert {"users", "auth_sessions"} <= set(sa.inspect(engine).get_table_names())

    command.downgrade(config, "base")
    assert set(sa.inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
