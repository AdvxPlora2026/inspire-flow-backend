from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.schemas.health import HealthResponse


def build_health_response(settings: Settings) -> HealthResponse:
    return HealthResponse(
        service=settings.name,
        environment=settings.environment,
    )
