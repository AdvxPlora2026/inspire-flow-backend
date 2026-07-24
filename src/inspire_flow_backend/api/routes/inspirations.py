from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import get_current_session
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.errors import ErrorResponse
from inspire_flow_backend.schemas.inspirations import (
    InspirationCreate,
    InspirationPage,
    InspirationPublic,
    InspirationSortBy,
    InspirationSourceType,
    InspirationStatus,
    InspirationUpdate,
    SortOrder,
)
from inspire_flow_backend.services import inspirations as inspiration_service
from inspire_flow_backend.services.sessions import AuthenticatedSession

router = APIRouter()

AUTH_RESPONSES = {401: {"model": ErrorResponse}}
INSPIRATION_RESPONSES = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}


@router.post(
    "",
    response_model=InspirationPublic,
    status_code=status.HTTP_201_CREATED,
    responses={
        **AUTH_RESPONSES,
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def create_inspiration(
    payload: InspirationCreate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> InspirationPublic:
    inspiration = inspiration_service.create_inspiration(
        db,
        authenticated.user.id,
        payload,
    )
    return inspiration_service.to_public_inspiration(inspiration)


@router.get(
    "",
    response_model=InspirationPage,
    responses={
        **AUTH_RESPONSES,
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def list_inspirations(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    project_id: UUID | None = None,
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


@router.get(
    "/{inspiration_id}",
    response_model=InspirationPublic,
    responses=INSPIRATION_RESPONSES,
)
def read_inspiration(
    inspiration_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> InspirationPublic:
    inspiration = inspiration_service.get_inspiration(
        db,
        authenticated.user.id,
        inspiration_id,
    )
    return inspiration_service.to_public_inspiration(inspiration)


@router.patch(
    "/{inspiration_id}",
    response_model=InspirationPublic,
    responses={
        **INSPIRATION_RESPONSES,
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def patch_inspiration(
    inspiration_id: UUID,
    payload: InspirationUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> InspirationPublic:
    inspiration = inspiration_service.update_inspiration(
        db,
        authenticated.user.id,
        inspiration_id,
        payload,
    )
    return inspiration_service.to_public_inspiration(inspiration)


@router.delete(
    "/{inspiration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=INSPIRATION_RESPONSES,
)
def remove_inspiration(
    inspiration_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    inspiration_service.delete_inspiration(
        db,
        authenticated.user.id,
        inspiration_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{inspiration_id}/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=INSPIRATION_RESPONSES,
)
def add_project_link(
    inspiration_id: UUID,
    project_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    inspiration_service.add_project_link(
        db,
        authenticated.user.id,
        inspiration_id,
        project_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{inspiration_id}/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **INSPIRATION_RESPONSES,
        409: {"model": ErrorResponse},
    },
)
def remove_project_link(
    inspiration_id: UUID,
    project_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    inspiration_service.remove_project_link(
        db,
        authenticated.user.id,
        inspiration_id,
        project_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
