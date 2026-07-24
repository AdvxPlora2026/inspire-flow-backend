from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from inspire_flow_backend.core.config import ModelSettings, Settings
from inspire_flow_backend.schemas.health import HealthResponse, HealthServices


def build_health_response(
    settings: Settings,
    model_settings: ModelSettings,
    db: Session,
) -> HealthResponse:
    database_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database_status = "unavailable"

    model_status = (
        "ok"
        if model_settings.api_key is not None
        and model_settings.name is not None
        and model_settings.base_url is not None
        else "not_configured"
    )
    overall_status = "unavailable" if database_status == "unavailable" else "degraded"
    return HealthResponse(
        status=overall_status,
        services=HealthServices(
            database=database_status,
            model=model_status,
        ),
        version=settings.version,
        service=settings.name,
        environment=settings.environment,
    )
