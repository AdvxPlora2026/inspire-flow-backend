from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from inspire_flow_backend.core.config import (
    ModelSettings,
    Settings,
    get_model_settings,
    get_settings,
)
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.health import HealthResponse
from inspire_flow_backend.services.health import build_health_response

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
def health_check(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    model_settings: Annotated[ModelSettings, Depends(get_model_settings)],
    db: Annotated[Session, Depends(get_db_session)],
) -> HealthResponse:
    health = build_health_response(settings, model_settings, db)
    if health.status == "unavailable":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health
