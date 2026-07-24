from typing import Literal

from pydantic import BaseModel


class HealthServices(BaseModel):
    database: Literal["ok", "unavailable"]
    model: Literal["ok", "not_configured"]
    injective: Literal["not_configured"] = "not_configured"


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    services: HealthServices
    version: str
    service: str
    environment: str
