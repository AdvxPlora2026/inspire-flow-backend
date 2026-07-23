from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.database import (
    create_database_engine,
    get_db_session,
)
from inspire_flow_backend.data.models.auth_session import AuthSession
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.main import create_app


@pytest.fixture
def db_session_factory(
    tmp_path: Path,
) -> Generator[sessionmaker[Session]]:
    database_path = tmp_path / "api.db"
    test_engine = create_database_engine(f"sqlite:///{database_path}")
    assert {AuthSession.__tablename__, User.__tablename__} <= set(Base.metadata.tables)
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def client(
    db_session_factory: sessionmaker[Session],
) -> Generator[TestClient]:
    application = create_app()

    def override_db_session() -> Generator[Session]:
        with db_session_factory() as db:
            yield db

    application.dependency_overrides[get_db_session] = override_db_session
    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()
