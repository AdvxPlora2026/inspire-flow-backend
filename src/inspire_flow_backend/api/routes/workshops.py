from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import (
    get_context_cipher,
    get_current_session,
    get_optional_session,
)
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.errors import ErrorResponse
from inspire_flow_backend.schemas.workshops import (
    WorkshopBrandAuthorizationPublic,
    WorkshopContactCreate,
    WorkshopContactPublic,
    WorkshopContactUpdate,
    WorkshopDraftPublic,
    WorkshopPreviewAudience,
    WorkshopProjectCardPublic,
    WorkshopProjectSelectionUpdate,
    WorkshopPublic,
    WorkshopSocialAccountCreate,
    WorkshopSocialAccountPublic,
    WorkshopSocialAccountUpdate,
    WorkshopUpdate,
)
from inspire_flow_backend.services import workshops as workshop_service
from inspire_flow_backend.services.sessions import AuthenticatedSession

owner_router = APIRouter()
public_router = APIRouter()

AUTH_RESPONSES = {401: {"model": ErrorResponse}}
WORKSHOP_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


@owner_router.get("", response_model=WorkshopDraftPublic, responses=AUTH_RESPONSES)
def read_my_workshop(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
) -> WorkshopDraftPublic:
    return workshop_service.get_draft(db, authenticated.user, cipher)


@owner_router.patch(
    "",
    response_model=WorkshopDraftPublic,
    responses={**WORKSHOP_RESPONSES, 422: {"model": ErrorResponse}},
)
def patch_my_workshop(
    payload: WorkshopUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
) -> WorkshopDraftPublic:
    return workshop_service.update_draft(db, authenticated.user, payload, cipher)


@owner_router.get(
    "/preview",
    response_model=WorkshopPublic,
    responses=WORKSHOP_RESPONSES,
)
def preview_my_workshop(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
    audience: Annotated[WorkshopPreviewAudience, Query()] = WorkshopPreviewAudience.owner,
) -> WorkshopPublic:
    return workshop_service.preview_workshop(
        db,
        authenticated.user,
        audience,
        cipher,
    )


@owner_router.post(
    "/publish",
    response_model=WorkshopPublic,
    responses=WORKSHOP_RESPONSES,
)
def publish_my_workshop(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
) -> WorkshopPublic:
    return workshop_service.publish_workshop(db, authenticated.user, cipher)


@owner_router.post(
    "/withdraw",
    response_model=WorkshopDraftPublic,
    responses=WORKSHOP_RESPONSES,
)
def withdraw_my_workshop(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
) -> WorkshopDraftPublic:
    return workshop_service.withdraw_workshop(
        db,
        authenticated.user.id,
        cipher,
    )


@owner_router.post(
    "/social-accounts",
    response_model=WorkshopSocialAccountPublic,
    status_code=status.HTTP_201_CREATED,
    responses=WORKSHOP_RESPONSES,
)
def create_social_account(
    payload: WorkshopSocialAccountCreate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> WorkshopSocialAccountPublic:
    return workshop_service.create_social_account(db, authenticated.user, payload)


@owner_router.patch(
    "/social-accounts/{account_id}",
    response_model=WorkshopSocialAccountPublic,
    responses=WORKSHOP_RESPONSES,
)
def patch_social_account(
    account_id: UUID,
    payload: WorkshopSocialAccountUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> WorkshopSocialAccountPublic:
    return workshop_service.update_social_account(
        db,
        authenticated.user.id,
        account_id,
        payload,
    )


@owner_router.delete(
    "/social-accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WORKSHOP_RESPONSES,
)
def remove_social_account(
    account_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    workshop_service.delete_social_account(
        db,
        authenticated.user.id,
        account_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@owner_router.post(
    "/contacts",
    response_model=WorkshopContactPublic,
    status_code=status.HTTP_201_CREATED,
    responses=WORKSHOP_RESPONSES,
)
def create_contact(
    payload: WorkshopContactCreate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
) -> WorkshopContactPublic:
    return workshop_service.create_contact(
        db,
        authenticated.user,
        payload,
        cipher,
    )


@owner_router.patch(
    "/contacts/{contact_id}",
    response_model=WorkshopContactPublic,
    responses=WORKSHOP_RESPONSES,
)
def patch_contact(
    contact_id: UUID,
    payload: WorkshopContactUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
) -> WorkshopContactPublic:
    return workshop_service.update_contact(
        db,
        authenticated.user.id,
        contact_id,
        payload,
        cipher,
    )


@owner_router.delete(
    "/contacts/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WORKSHOP_RESPONSES,
)
def remove_contact(
    contact_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    workshop_service.delete_contact(db, authenticated.user.id, contact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@owner_router.put(
    "/projects/{project_id}",
    response_model=WorkshopProjectCardPublic,
    responses=WORKSHOP_RESPONSES,
)
def set_project_selection(
    project_id: UUID,
    payload: WorkshopProjectSelectionUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> WorkshopProjectCardPublic:
    return workshop_service.set_project_selection(
        db,
        authenticated.user,
        project_id,
        payload,
    )


@owner_router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WORKSHOP_RESPONSES,
)
def remove_project_selection(
    project_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    workshop_service.delete_project_selection(
        db,
        authenticated.user.id,
        project_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@owner_router.get(
    "/brand-authorizations",
    response_model=list[WorkshopBrandAuthorizationPublic],
    responses=WORKSHOP_RESPONSES,
)
def list_my_brand_authorizations(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> list[WorkshopBrandAuthorizationPublic]:
    return workshop_service.list_brand_authorizations(db, authenticated.user.id)


@owner_router.put(
    "/brand-authorizations/{brand_id}",
    response_model=WorkshopBrandAuthorizationPublic,
    responses=WORKSHOP_RESPONSES,
)
def grant_brand_authorization(
    brand_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> WorkshopBrandAuthorizationPublic:
    return workshop_service.grant_brand_authorization(
        db,
        authenticated.user.id,
        brand_id,
    )


@owner_router.delete(
    "/brand-authorizations/{brand_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WORKSHOP_RESPONSES,
)
def revoke_brand_authorization(
    brand_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    workshop_service.revoke_brand_authorization(
        db,
        authenticated.user.id,
        brand_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public_router.get(
    "/{creator_id}",
    response_model=WorkshopPublic,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def read_public_workshop(
    creator_id: UUID,
    authenticated: Annotated[
        AuthenticatedSession | None,
        Depends(get_optional_session),
    ],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
    brand_id: UUID | None = None,
) -> WorkshopPublic:
    return workshop_service.read_public_workshop(
        db,
        creator_id,
        viewer_user_id=authenticated.user.id if authenticated else None,
        brand_id=brand_id,
        cipher=cipher,
    )
