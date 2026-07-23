from typing import Annotated

from fastapi import APIRouter, Depends

from inspire_flow_backend.core.config import Settings, get_settings
from inspire_flow_backend.schemas.health import HealthResponse
from inspire_flow_backend.services.health import build_health_response

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    return build_health_response(settings)
