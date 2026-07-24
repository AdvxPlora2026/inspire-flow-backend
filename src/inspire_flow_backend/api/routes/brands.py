from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import get_current_session
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.brands import (
    BrandCreate,
    BrandInvitationCreate,
    BrandInvitationPublic,
    BrandMembershipPublic,
    BrandMemberUpdate,
    BrandPage,
    BrandPublic,
    BrandUpdate,
)
from inspire_flow_backend.schemas.errors import ErrorResponse
from inspire_flow_backend.services import brands as brand_service
from inspire_flow_backend.services.sessions import AuthenticatedSession

router = APIRouter()
invitation_router = APIRouter()

AUTH_RESPONSES = {401: {"model": ErrorResponse}}
BRAND_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


@router.post(
    "",
    response_model=BrandPublic,
    status_code=status.HTTP_201_CREATED,
    responses={**AUTH_RESPONSES, 422: {"model": ErrorResponse}},
)
def create_brand(
    payload: BrandCreate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> BrandPublic:
    return brand_service.create_brand(db, authenticated.user.id, payload)


@router.get("", response_model=BrandPage, responses=AUTH_RESPONSES)
def list_brands(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BrandPage:
    return brand_service.list_brands(
        db,
        authenticated.user.id,
        limit=limit,
        offset=offset,
    )


@router.get("/{brand_id}", response_model=BrandPublic, responses=BRAND_RESPONSES)
def read_brand(
    brand_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> BrandPublic:
    return brand_service.read_brand(db, brand_id, authenticated.user.id)


@router.patch("/{brand_id}", response_model=BrandPublic, responses=BRAND_RESPONSES)
def patch_brand(
    brand_id: UUID,
    payload: BrandUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> BrandPublic:
    return brand_service.update_brand(
        db,
        brand_id,
        authenticated.user.id,
        payload,
    )


@router.get(
    "/{brand_id}/members",
    response_model=list[BrandMembershipPublic],
    responses=BRAND_RESPONSES,
)
def list_brand_members(
    brand_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> list[BrandMembershipPublic]:
    return brand_service.list_members(db, brand_id, authenticated.user.id)


@router.patch(
    "/{brand_id}/members/{user_id}",
    response_model=BrandMembershipPublic,
    responses=BRAND_RESPONSES,
)
def patch_brand_member(
    brand_id: UUID,
    user_id: UUID,
    payload: BrandMemberUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> BrandMembershipPublic:
    return brand_service.update_member(
        db,
        brand_id,
        user_id,
        authenticated.user.id,
        payload,
    )


@router.delete(
    "/{brand_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=BRAND_RESPONSES,
)
def remove_brand_member(
    brand_id: UUID,
    user_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    brand_service.remove_member(
        db,
        brand_id,
        user_id,
        authenticated.user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{brand_id}/invitations",
    response_model=BrandInvitationPublic,
    status_code=status.HTTP_201_CREATED,
    responses=BRAND_RESPONSES,
)
def create_brand_invitation(
    brand_id: UUID,
    payload: BrandInvitationCreate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> BrandInvitationPublic:
    return brand_service.create_invitation(
        db,
        brand_id,
        authenticated.user.id,
        payload,
    )


@router.delete(
    "/{brand_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=BRAND_RESPONSES,
)
def revoke_brand_invitation(
    brand_id: UUID,
    invitation_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    brand_service.revoke_invitation(
        db,
        brand_id,
        invitation_id,
        authenticated.user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@invitation_router.get(
    "",
    response_model=list[BrandInvitationPublic],
    responses=AUTH_RESPONSES,
)
def list_my_brand_invitations(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> list[BrandInvitationPublic]:
    return brand_service.list_invitations(db, authenticated.user.id)


@invitation_router.post(
    "/{invitation_id}/accept",
    response_model=BrandInvitationPublic,
    responses=BRAND_RESPONSES,
)
def accept_brand_invitation(
    invitation_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> BrandInvitationPublic:
    return brand_service.respond_to_invitation(
        db,
        invitation_id,
        authenticated.user.id,
        accept=True,
    )


@invitation_router.post(
    "/{invitation_id}/decline",
    response_model=BrandInvitationPublic,
    responses=BRAND_RESPONSES,
)
def decline_brand_invitation(
    invitation_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> BrandInvitationPublic:
    return brand_service.respond_to_invitation(
        db,
        invitation_id,
        authenticated.user.id,
        accept=False,
    )
