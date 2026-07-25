from fastapi import APIRouter

from inspire_flow_backend.api.routes.advisory import router as advisory_router
from inspire_flow_backend.api.routes.brands import (
    invitation_router as brand_invitations_router,
)
from inspire_flow_backend.api.routes.brands import router as brands_router
from inspire_flow_backend.api.routes.commercial_tasks import (
    router as commercial_tasks_router,
)
from inspire_flow_backend.api.routes.conversations import (
    router as conversations_router,
)
from inspire_flow_backend.api.routes.engagement import (
    brand_router as brand_engagement_router,
)
from inspire_flow_backend.api.routes.engagement import (
    creator_router as creator_engagement_router,
)
from inspire_flow_backend.api.routes.health import router as health_router
from inspire_flow_backend.api.routes.inspirations import (
    router as inspirations_router,
)
from inspire_flow_backend.api.routes.memories import router as memories_router
from inspire_flow_backend.api.routes.projects import router as projects_router
from inspire_flow_backend.api.routes.sessions import router as sessions_router
from inspire_flow_backend.api.routes.transcriptions import (
    router as transcriptions_router,
)
from inspire_flow_backend.api.routes.users import router as users_router
from inspire_flow_backend.api.routes.workshops import owner_router as workshop_owner_router
from inspire_flow_backend.api.routes.workshops import public_router as workshops_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(
    conversations_router,
    prefix="/conversations",
    tags=["conversations"],
)
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(
    inspirations_router,
    prefix="/inspirations",
    tags=["inspirations"],
)
api_router.include_router(projects_router, prefix="/projects", tags=["projects"])
api_router.include_router(
    commercial_tasks_router,
    prefix="/commercial-tasks",
    tags=["commercial-tasks"],
)
api_router.include_router(brands_router, prefix="/brands", tags=["brands"])
api_router.include_router(advisory_router, prefix="/brands", tags=["brand-advisory"])
api_router.include_router(
    brand_engagement_router,
    prefix="/brands",
    tags=["brand-engagement"],
)
api_router.include_router(
    creator_engagement_router,
    prefix="/users/me",
    tags=["brand-engagement"],
)
api_router.include_router(
    brand_invitations_router,
    prefix="/users/me/brand-invitations",
    tags=["brands"],
)
api_router.include_router(
    workshop_owner_router,
    prefix="/users/me/workshop",
    tags=["workshops"],
)
api_router.include_router(
    workshops_router,
    prefix="/workshops",
    tags=["workshops"],
)
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
