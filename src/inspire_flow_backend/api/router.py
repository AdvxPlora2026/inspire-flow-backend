from fastapi import APIRouter

from inspire_flow_backend.api.routes.conversations import (
    router as conversations_router,
)
from inspire_flow_backend.api.routes.health import router as health_router
from inspire_flow_backend.api.routes.memories import router as memories_router
from inspire_flow_backend.api.routes.sessions import router as sessions_router
from inspire_flow_backend.api.routes.transcriptions import (
    router as transcriptions_router,
)
from inspire_flow_backend.api.routes.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(
    conversations_router,
    prefix="/conversations",
    tags=["conversations"],
)
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(
    memories_router,
    prefix="/users/me/memories",
    tags=["memories"],
)
api_router.include_router(sessions_router, prefix="/sessions", tags=["sessions"])
api_router.include_router(
    transcriptions_router,
    prefix="/transcriptions",
    tags=["transcriptions"],
)
