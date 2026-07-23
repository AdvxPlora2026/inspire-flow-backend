from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def test_migration_upgrades_and_downgrades_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")

    engine = sa.create_engine(f"sqlite:///{database_path}")
    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) >= {
        "alembic_version",
        "users",
        "auth_sessions",
    }
    assert {column["name"] for column in inspector.get_columns("users")} == {
        "id",
        "nickname",
        "nickname_key",
        "avatar_url",
        "password_hash",
        "created_at",
        "updated_at",
    }
    assert {column["name"] for column in inspector.get_columns("auth_sessions")} == {
        "id",
        "user_id",
        "token_hash",
        "expires_at",
        "created_at",
    }
    assert {constraint["name"] for constraint in inspector.get_unique_constraints("users")} == {
        "uq_users_nickname_key"
    }
    assert {
        constraint["name"] for constraint in inspector.get_unique_constraints("auth_sessions")
    } == {"uq_auth_sessions_token_hash"}
    foreign_keys = inspector.get_foreign_keys("auth_sessions")
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["constrained_columns"] == ["user_id"]
    assert foreign_keys[0]["referred_table"] == "users"
    assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"
    assert {index["name"] for index in inspector.get_indexes("auth_sessions")} == {
        "ix_auth_sessions_user_id"
    }

    command.downgrade(config, "base")

    assert set(sa.inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
