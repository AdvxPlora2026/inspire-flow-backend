from fastapi import APIRouter

from inspire_flow_backend.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
