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
STT_TABLES = {"transcription_jobs"}
PROJECT_TABLES = {"projects"}
INSPIRATION_TABLES = {"inspirations", "inspiration_projects"}


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
        *STT_TABLES,
        *PROJECT_TABLES,
        *INSPIRATION_TABLES,
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
    assert {column["name"] for column in inspector.get_columns("transcription_jobs")} == {
        "id",
        "user_id",
        "status",
        "language",
        "use_itn",
        "transcript_ciphertext",
        "analysis_ciphertext",
        "detected_language",
        "duration_seconds",
        "error_code",
        "attempt_count",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    }
    assert {column["name"] for column in inspector.get_columns("projects")} == {
        "id",
        "user_id",
        "title",
        "type",
        "audience",
        "summary",
        "icon_url",
        "created_at",
        "updated_at",
    }
    assert {column["name"] for column in inspector.get_columns("inspirations")} == {
        "id",
        "user_id",
        "title",
        "content",
        "status",
        "source_type",
        "source_conversation_id",
        "source_message_id",
        "created_at",
        "updated_at",
    }
    assert {column["name"] for column in inspector.get_columns("inspiration_projects")} == {
        "inspiration_id",
        "project_id",
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
    assert {
        "ck_transcription_jobs_status_valid",
        "ck_transcription_jobs_attempt_count_nonnegative",
    } <= named_constraints(inspector, "transcription_jobs", "get_check_constraints")
    assert {
        "ck_inspirations_status_valid",
        "ck_inspirations_source_type_valid",
    } <= named_constraints(inspector, "inspirations", "get_check_constraints")

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
    assert {index["name"] for index in inspector.get_indexes("transcription_jobs")} == {
        "ix_transcription_jobs_user_id_created_at",
    }
    assert {index["name"] for index in inspector.get_indexes("projects")} == {
        "ix_projects_user_id_updated_at",
    }
    assert {index["name"] for index in inspector.get_indexes("inspirations")} == {
        "ix_inspirations_source_conversation_id",
        "ix_inspirations_source_message_id",
        "ix_inspirations_user_id_status_updated_at",
        "ix_inspirations_user_id_updated_at",
    }
    assert {index["name"] for index in inspector.get_indexes("inspiration_projects")} == {
        "ix_inspiration_projects_project_id_inspiration_id"
    }

    expected_foreign_keys = {
        ("user_profiles", "user_id"): ("users", "CASCADE"),
        ("agent_conversations", "user_id"): ("users", "CASCADE"),
        ("agent_messages", "conversation_id"): ("agent_conversations", "CASCADE"),
        ("user_memories", "user_id"): ("users", "CASCADE"),
        ("user_memories", "source_conversation_id"): ("agent_conversations", "SET NULL"),
        ("user_memories", "source_message_id"): ("agent_messages", "SET NULL"),
        ("transcription_jobs", "user_id"): ("users", "CASCADE"),
        ("projects", "user_id"): ("users", "CASCADE"),
        ("inspirations", "user_id"): ("users", "CASCADE"),
        ("inspirations", "source_conversation_id"): (
            "agent_conversations",
            "SET NULL",
        ),
        ("inspirations", "source_message_id"): ("agent_messages", "SET NULL"),
        ("inspiration_projects", "inspiration_id"): ("inspirations", "CASCADE"),
        ("inspiration_projects", "project_id"): ("projects", "CASCADE"),
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
    assert (CONTEXT_TABLES | STT_TABLES | PROJECT_TABLES | INSPIRATION_TABLES).isdisjoint(
        sa.inspect(engine).get_table_names()
    )
    assert {"users", "auth_sessions"} <= set(sa.inspect(engine).get_table_names())

    command.downgrade(config, "base")
    assert set(sa.inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()


def test_metadata_migration_preserves_existing_transcription_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "existing-stt.db"
    config = make_config(database_path)
    command.upgrade(config, "20260724_0003")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    user_id = uuid4()
    job_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO users (
                    id, nickname, nickname_key, avatar_url, password_hash, created_at, updated_at
                ) VALUES (
                    :id, 'Creator', 'creator', NULL, 'test-only-hash', :now, :now
                )
                """
            ),
            {"id": user_id.hex, "now": now},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO transcription_jobs (
                    id, user_id, status, language, use_itn, transcript_ciphertext,
                    detected_language, duration_seconds, error_code, attempt_count,
                    started_at, completed_at, created_at, updated_at
                ) VALUES (
                    :id, :user_id, 'succeeded', 'zh', 1, 'encrypted-transcript',
                    'zh', 2.5, NULL, 1, :now, :now, :now, :now
                )
                """
            ),
            {"id": job_id.hex, "user_id": user_id.hex, "now": now},
        )

    command.upgrade(config, "head")

    columns = {column["name"] for column in sa.inspect(engine).get_columns("transcription_jobs")}
    assert "analysis_ciphertext" in columns
    with engine.connect() as connection:
        row = connection.execute(
            sa.text(
                """
                SELECT transcript_ciphertext, analysis_ciphertext
                FROM transcription_jobs
                WHERE id = :id
                """
            ),
            {"id": job_id.hex},
        ).one()
    assert row.transcript_ciphertext == "encrypted-transcript"
    assert row.analysis_ciphertext is None

    command.downgrade(config, "20260724_0003")
    assert "analysis_ciphertext" not in {
        column["name"] for column in sa.inspect(engine).get_columns("transcription_jobs")
    }
    engine.dispose()


def test_project_migration_upgrades_existing_database_and_downgrades(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "existing-projects.db"
    config = make_config(database_path)
    command.upgrade(config, "20260724_0004")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    user_id = uuid4()
    project_id = uuid4()
    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        connection.execute(
            sa.text(
                """
                INSERT INTO users (
                    id, nickname, nickname_key, avatar_url, password_hash, created_at, updated_at
                ) VALUES (
                    :id, 'Creator', 'creator-project', NULL, 'test-only-hash', :now, :now
                )
                """
            ),
            {"id": user_id.hex, "now": now},
        )

    command.upgrade(config, "head")

    assert "projects" in sa.inspect(engine).get_table_names()
    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        connection.execute(
            sa.text(
                """
                INSERT INTO projects (
                    id, user_id, title, type, audience, summary, created_at, updated_at
                ) VALUES (
                    :id, :user_id, 'Title', '科技数码', '创作者', 'Summary', :now, :now
                )
                """
            ),
            {"id": project_id.hex, "user_id": user_id.hex, "now": now},
        )
        connection.execute(
            sa.text("DELETE FROM users WHERE id = :id"),
            {"id": user_id.hex},
        )
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM projects")) == 0

    command.downgrade(config, "20260724_0004")
    assert "projects" not in sa.inspect(engine).get_table_names()
    assert "users" in sa.inspect(engine).get_table_names()
    engine.dispose()


def test_project_icon_migration_preserves_existing_project_rows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "existing-project-icon.db"
    config = make_config(database_path)
    command.upgrade(config, "20260724_0005")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    user_id = uuid4()
    project_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO users (
                    id, nickname, nickname_key, avatar_url, password_hash, created_at, updated_at
                ) VALUES (
                    :id, 'Icon Creator', 'icon-creator', NULL, 'test-only-hash', :now, :now
                )
                """
            ),
            {"id": user_id.hex, "now": now},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO projects (
                    id, user_id, title, type, audience, summary, created_at, updated_at
                ) VALUES (
                    :id, :user_id, 'Title', '科技数码', '创作者', 'Summary', :now, :now
                )
                """
            ),
            {"id": project_id.hex, "user_id": user_id.hex, "now": now},
        )

    command.upgrade(config, "head")

    assert "icon_url" in {column["name"] for column in sa.inspect(engine).get_columns("projects")}
    with engine.begin() as connection:
        assert (
            connection.scalar(
                sa.text("SELECT icon_url FROM projects WHERE id = :id"),
                {"id": project_id.hex},
            )
            is None
        )
        connection.execute(
            sa.text("UPDATE projects SET icon_url = :icon_url WHERE id = :id"),
            {
                "id": project_id.hex,
                "icon_url": "https://cdn.example.com/project.png",
            },
        )

    command.downgrade(config, "20260724_0005")

    assert "icon_url" not in {
        column["name"] for column in sa.inspect(engine).get_columns("projects")
    }
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text("SELECT COUNT(*) FROM projects WHERE id = :id"),
                {"id": project_id.hex},
            )
            == 1
        )
    engine.dispose()


def test_user_profile_text_migration_preserves_existing_users(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "existing-user-profile-text.db"
    config = make_config(database_path)
    command.upgrade(config, "20260724_0007")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    user_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO users (
                    id, nickname, nickname_key, avatar_url, password_hash, created_at, updated_at
                ) VALUES (
                    :id, 'Profile Creator', 'profile-creator', NULL,
                    'test-only-hash', :now, :now
                )
                """
            ),
            {"id": user_id.hex, "now": now},
        )

    command.upgrade(config, "head")

    assert "profile_text" in {column["name"] for column in sa.inspect(engine).get_columns("users")}
    with engine.begin() as connection:
        assert (
            connection.scalar(
                sa.text("SELECT profile_text FROM users WHERE id = :id"),
                {"id": user_id.hex},
            )
            is None
        )
        connection.execute(
            sa.text("UPDATE users SET profile_text = :profile_text WHERE id = :id"),
            {"id": user_id.hex, "profile_text": "偏好科技内容"},
        )

    command.downgrade(config, "20260724_0007")

    assert "profile_text" not in {
        column["name"] for column in sa.inspect(engine).get_columns("users")
    }
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.text("SELECT COUNT(*) FROM users WHERE id = :id"),
                {"id": user_id.hex},
            )
            == 1
        )
    engine.dispose()
