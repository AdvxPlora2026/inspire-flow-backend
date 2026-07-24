from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import (
    get_agent_runtime,
    get_current_session,
)
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.errors import (
    ErrorResponse,
    ResourceImpactErrorResponse,
)
from inspire_flow_backend.schemas.inspirations import (
    InspirationPage,
    InspirationSortBy,
    InspirationSourceType,
    InspirationStatus,
    SortOrder,
)
from inspire_flow_backend.schemas.projects import (
    ProjectCreate,
    ProjectDetail,
    ProjectDraft,
    ProjectDraftRequest,
    ProjectPage,
    ProjectPublic,
    ProjectUpdate,
)
from inspire_flow_backend.services import inspirations as inspiration_service
from inspire_flow_backend.services import projects as project_service
from inspire_flow_backend.services.agent.runtime import AgentRuntime
from inspire_flow_backend.services.sessions import AuthenticatedSession

router = APIRouter()

AUTH_RESPONSES = {401: {"model": ErrorResponse}}
PROJECT_RESPONSES = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}


@router.post(
    "/drafts",
    response_model=ProjectDraft,
    responses={
        401: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_project_draft(
    payload: ProjectDraftRequest,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    runtime: Annotated[AgentRuntime, Depends(get_agent_runtime)],
) -> ProjectDraft:
    del authenticated
    return await project_service.draft_project(
        payload.description,
        runtime.project_draft_generator,
    )


@router.post(
    "",
    response_model=ProjectPublic,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def create_project(
    payload: ProjectCreate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> ProjectPublic:
    project = project_service.create_project(db, authenticated.user.id, payload)
    return ProjectPublic.model_validate(project)


@router.get(
    "",
    response_model=ProjectPage,
    responses=AUTH_RESPONSES,
)
def list_projects(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectPage:
    return project_service.list_projects(
        db,
        authenticated.user.id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectDetail,
    responses=PROJECT_RESPONSES,
)
def read_project(
    project_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> ProjectDetail:
    return project_service.get_project_detail(
        db,
        authenticated.user.id,
        project_id,
    )


@router.get(
    "/{project_id}/inspirations",
    response_model=InspirationPage,
    responses={
        **PROJECT_RESPONSES,
        422: {"model": ErrorResponse},
    },
)
def read_project_inspirations(
    project_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    status_filter: Annotated[
        InspirationStatus | None,
        Query(alias="status"),
    ] = None,
    source_type: InspirationSourceType | None = None,
    query: Annotated[str | None, Query(max_length=300)] = None,
    sort_by: InspirationSortBy = InspirationSortBy.updated_at,
    sort_order: SortOrder = SortOrder.desc,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InspirationPage:
    return inspiration_service.list_inspirations(
        db,
        authenticated.user.id,
        project_id=project_id,
        status=status_filter,
        source_type=source_type,
        query=query,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/{project_id}",
    response_model=ProjectPublic,
    responses={
        **PROJECT_RESPONSES,
        422: {"model": ErrorResponse},
    },
)
def patch_project(
    project_id: UUID,
    payload: ProjectUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> ProjectPublic:
    project = project_service.update_project(
        db,
        authenticated.user.id,
        project_id,
        payload,
    )
    return ProjectPublic.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **PROJECT_RESPONSES,
        409: {"model": ResourceImpactErrorResponse},
    },
)
def remove_project(
    project_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    delete_orphan_inspirations: bool = False,
) -> Response:
    project_service.delete_project(
        db,
        authenticated.user.id,
        project_id,
        delete_orphan_inspirations=delete_orphan_inspirations,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
