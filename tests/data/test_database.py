from pathlib import Path

from sqlalchemy import text

from inspire_flow_backend.data.database import create_database_engine


def test_enables_sqlite_foreign_keys(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'foreign-keys.db'}")

    with engine.connect() as connection:
        enabled = connection.scalar(text("PRAGMA foreign_keys"))

    assert enabled == 1
    engine.dispose()


def test_configures_sqlite_for_bounded_cross_process_writes(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'concurrent.db'}")

    with engine.connect() as connection:
        journal_mode = connection.scalar(text("PRAGMA journal_mode"))
        busy_timeout = connection.scalar(text("PRAGMA busy_timeout"))

    assert journal_mode == "wal"
    assert busy_timeout == 5_000
    engine.dispose()
