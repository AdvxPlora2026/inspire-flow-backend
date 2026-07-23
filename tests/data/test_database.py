from pathlib import Path

from sqlalchemy import text

from inspire_flow_backend.data.database import create_database_engine


def test_enables_sqlite_foreign_keys(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'foreign-keys.db'}")

    with engine.connect() as connection:
        enabled = connection.scalar(text("PRAGMA foreign_keys"))

    assert enabled == 1
    engine.dispose()
