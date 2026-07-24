from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.config import get_settings


def enable_sqlite_foreign_keys(engine: Engine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def create_database_engine(database_url: str) -> Engine:
    connect_args: dict[str, bool] = {}
    if make_url(database_url).get_backend_name() == "sqlite":
        connect_args["check_same_thread"] = False
    database_engine = create_engine(database_url, connect_args=connect_args)
    enable_sqlite_foreign_keys(database_engine)
    return database_engine


engine = create_database_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db_session() -> Generator[Session]:
    with SessionLocal() as db:
        yield db
