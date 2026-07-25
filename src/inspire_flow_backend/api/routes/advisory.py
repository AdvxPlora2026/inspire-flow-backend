from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import get_agent_runtime, get_current_session
from inspire_flow_backend.core.errors import AgentUnavailableError
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.advisory import BrandAdvisoryReport, BrandAdvisoryRequest
from inspire_flow_backend.schemas.errors import ErrorResponse
from inspire_flow_backend.services import advisory as advisory_service
from inspire_flow_backend.services.agent.runtime import AgentRuntime
from inspire_flow_backend.services.sessions import AuthenticatedSession

router = APIRouter()


@router.post(
    "/{brand_id}/advisory-reports",
    response_model=BrandAdvisoryReport,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def create_advisory_report(
    brand_id: UUID,
    payload: BrandAdvisoryRequest,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    runtime: Annotated[AgentRuntime, Depends(get_agent_runtime)],
) -> BrandAdvisoryReport:
    if runtime.brand_advisor is None:
        raise AgentUnavailableError
    return await advisory_service.analyze_brand_project(
        db,
        authenticated.user.id,
        brand_id,
        payload,
        runtime.brand_advisor,
    )
