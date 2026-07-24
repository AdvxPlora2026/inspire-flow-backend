from pathlib import Path

import sqlalchemy as sa
from alembic import command

from tests.data.test_migrations import make_config

COMMERCIAL_TABLES = {
    "commercial_tasks",
    "commercial_task_splits",
    "commercial_task_submissions",
    "chain_transactions",
}


def test_commercial_migration_is_reversible(tmp_path: Path) -> None:
    database_path = tmp_path / "commercial.db"
    config = make_config(database_path)

    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database_path}")
    inspector = sa.inspect(engine)

    assert COMMERCIAL_TABLES <= set(inspector.get_table_names())
    assert {
        "uq_commercial_task_splits_task_party",
    } == {str(item["name"]) for item in inspector.get_unique_constraints("commercial_task_splits")}
    assert {"memo", "transaction_hash", "explorer_url", "failure_reason", "retryable"} <= {
        str(column["name"]) for column in inspector.get_columns("chain_transactions")
    }
    assert {"ix_chain_transactions_task_id_created_at"} == {
        str(item["name"]) for item in inspector.get_indexes("chain_transactions")
    }

    command.downgrade(config, "20260724_0009")
    assert COMMERCIAL_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    assert {"users", "projects"} <= set(sa.inspect(engine).get_table_names())
    engine.dispose()
