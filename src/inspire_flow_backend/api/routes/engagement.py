from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import get_context_cipher, get_current_session
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.engagement import (
    BrandFollowPage,
    BrandFollowPublic,
    BrandInterestCreate,
    BrandInterestPage,
    BrandInterestPublic,
    BrandInterestUpdate,
    CreatorDiscoveryPage,
    CreatorInboxItemPublic,
    CreatorInboxItemUpdate,
    CreatorInboxMarkRead,
    CreatorInboxPage,
    CreatorInterestUpdate,
    DiscoverySortBy,
    DiscoverySortOrder,
)
from inspire_flow_backend.schemas.errors import ErrorResponse
from inspire_flow_backend.services import engagement as engagement_service
from inspire_flow_backend.services import workshops as workshop_service
from inspire_flow_backend.services.sessions import AuthenticatedSession

brand_router = APIRouter()
creator_router = APIRouter()

RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


@brand_router.get(
    "/{brand_id}/creator-discovery",
    response_model=CreatorDiscoveryPage,
    responses=RESPONSES,
)
def discover_creators(
    brand_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
    query: Annotated[str | None, Query(max_length=300)] = None,
    content_focus: Annotated[str | None, Query(max_length=100)] = None,
    creator_identity: Annotated[str | None, Query(max_length=100)] = None,
    project_type: Annotated[str | None, Query(max_length=50)] = None,
    followed: bool | None = None,
    sort_by: DiscoverySortBy = DiscoverySortBy.updated_at,
    sort_order: DiscoverySortOrder = DiscoverySortOrder.desc,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CreatorDiscoveryPage:
    return workshop_service.discover_workshops(
        db,
        brand_id,
        authenticated.user.id,
        query=query,
        content_focus=content_focus,
        creator_identity=creator_identity,
        project_type=project_type,
        followed=followed,
        sort_by=sort_by.value,
        sort_order=sort_order.value,
        limit=limit,
        offset=offset,
        cipher=cipher,
    )


@brand_router.get(
    "/{brand_id}/follows",
    response_model=BrandFollowPage,
    responses=RESPONSES,
)
def list_brand_follows(
    brand_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BrandFollowPage:
    return engagement_service.list_follows(
        db,
        brand_id,
        authenticated.user.id,
        limit=limit,
        offset=offset,
    )


@brand_router.put(
    "/{brand_id}/follows/{creator_id}",
    response_model=BrandFollowPublic,
    responses=RESPONSES,
)
def follow_creator(
    brand_id: UUID,
    creator_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> BrandFollowPublic:
    return engagement_service.follow_creator(
        db,
        brand_id,
        creator_id,
        authenticated.user.id,
    )


@brand_router.delete(
    "/{brand_id}/follows/{creator_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=RESPONSES,
)
def unfollow_creator(
    brand_id: UUID,
    creator_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    engagement_service.unfollow_creator(
        db,
        brand_id,
        creator_id,
        authenticated.user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@brand_router.get(
    "/{brand_id}/interests",
    response_model=BrandInterestPage,
    responses=RESPONSES,
)
def list_brand_interests(
    brand_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BrandInterestPage:
    return engagement_service.list_interests(
        db,
        brand_id,
        authenticated.user.id,
        limit=limit,
        offset=offset,
    )


@brand_router.post(
    "/{brand_id}/interests",
    response_model=BrandInterestPublic,
    status_code=status.HTTP_201_CREATED,
    responses=RESPONSES,
)
def create_brand_interest(
    brand_id: UUID,
    payload: BrandInterestCreate,
    response: Response,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> BrandInterestPublic:
    created = engagement_service.create_interest(
        db,
        brand_id,
        authenticated.user.id,
        payload,
    )
    response.status_code = 201 if created.created else 200
    return created.interest


@brand_router.patch(
    "/{brand_id}/interests/{interest_id}",
    response_model=BrandInterestPublic,
    responses=RESPONSES,
)
def withdraw_brand_interest(
    brand_id: UUID,
    interest_id: UUID,
    payload: BrandInterestUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> BrandInterestPublic:
    del payload
    return engagement_service.withdraw_interest(
        db,
        brand_id,
        interest_id,
        authenticated.user.id,
    )


@creator_router.get(
    "/brand-inbox",
    response_model=CreatorInboxPage,
    responses=RESPONSES,
)
def list_creator_inbox(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CreatorInboxPage:
    return engagement_service.list_creator_inbox(
        db,
        authenticated.user.id,
        limit=limit,
        offset=offset,
    )


@creator_router.patch(
    "/brand-inbox/{item_id}",
    response_model=CreatorInboxItemPublic,
    responses=RESPONSES,
)
def patch_creator_inbox_item(
    item_id: UUID,
    payload: CreatorInboxItemUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CreatorInboxItemPublic:
    return engagement_service.update_inbox_item(
        db,
        authenticated.user.id,
        item_id,
        payload,
    )


@creator_router.post(
    "/brand-inbox/mark-read",
    response_model=CreatorInboxPage,
    responses=RESPONSES,
)
def mark_creator_inbox_read(
    payload: CreatorInboxMarkRead,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CreatorInboxPage:
    return engagement_service.mark_inbox_read(
        db,
        authenticated.user.id,
        payload,
    )


@creator_router.patch(
    "/brand-interests/{interest_id}",
    response_model=BrandInterestPublic,
    responses=RESPONSES,
)
def respond_to_brand_interest(
    interest_id: UUID,
    payload: CreatorInterestUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> BrandInterestPublic:
    return engagement_service.respond_to_interest(
        db,
        authenticated.user.id,
        interest_id,
        payload,
    )
