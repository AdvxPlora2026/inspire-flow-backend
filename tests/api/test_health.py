from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from inspire_flow_backend.core.config import (
    ModelSettings,
    Settings,
    get_model_settings,
    get_settings,
)
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.main import create_app


class HealthProbeSession:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.statements: list[str] = []

    def execute(self, statement: object) -> None:
        self.statements.append(str(statement))
        if self.error is not None:
            raise self.error


def build_health_client(
    *,
    db: HealthProbeSession,
    model_settings: ModelSettings,
    injective_private_key: str | None = None,
) -> TestClient:
    application = create_app()

    def override_db_session() -> Generator[HealthProbeSession]:
        yield db

    application.dependency_overrides[get_db_session] = override_db_session
    application.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        name="Inspire Flow Test",
        environment="test",
        version="test-sha",
        injective_private_key=injective_private_key,
    )
    application.dependency_overrides[get_model_settings] = lambda: model_settings
    return TestClient(application)


def test_health_check_reports_degraded_until_injective_is_configured() -> None:
    db = HealthProbeSession()
    model_settings = ModelSettings(
        _env_file=None,
        api_key="test-key",
        name="test-model",
        base_url="https://model.example/v1",
    )

    with build_health_client(db=db, model_settings=model_settings) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "services": {
            "database": "ok",
            "model": "ok",
            "injective": "not_configured",
        },
        "version": "test-sha",
        "service": "Inspire Flow Test",
        "environment": "test",
    }
    assert db.statements == ["SELECT 1"]


def test_health_check_reports_ok_when_all_services_configured() -> None:
    db = HealthProbeSession()
    model_settings = ModelSettings(
        _env_file=None,
        api_key="test-key",
        name="test-model",
        base_url="https://model.example/v1",
    )

    with build_health_client(
        db=db,
        model_settings=model_settings,
        injective_private_key="0x" + "1" * 64,
    ) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["services"] == {
        "database": "ok",
        "model": "ok",
        "injective": "ok",
    }


def test_health_check_reports_missing_model_configuration() -> None:
    with build_health_client(
        db=HealthProbeSession(),
        model_settings=ModelSettings(_env_file=None),
    ) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["services"] == {
        "database": "ok",
        "model": "not_configured",
        "injective": "not_configured",
    }


def test_health_check_returns_503_without_leaking_database_error() -> None:
    distinctive_error = "private database host leaked"
    database_error = OperationalError(
        "SELECT 1",
        {},
        RuntimeError(distinctive_error),
    )
    with build_health_client(
        db=HealthProbeSession(database_error),
        model_settings=ModelSettings(_env_file=None),
    ) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["services"] == {
        "database": "unavailable",
        "model": "not_configured",
        "injective": "not_configured",
    }
    assert distinctive_error not in response.text


def test_health_endpoint_stays_under_existing_api_prefix() -> None:
    application = create_app()

    assert "/api/v1/health" in application.openapi()["paths"]
    assert "/v1/health" not in application.openapi()["paths"]
