from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import get_current_session
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.errors import ErrorResponse
from inspire_flow_backend.schemas.profiles import UserProfilePublic, UserProfileUpdate
from inspire_flow_backend.schemas.users import UserCreate, UserPublic, UserUpdate
from inspire_flow_backend.services.profiles import get_profile, update_profile
from inspire_flow_backend.services.sessions import AuthenticatedSession
from inspire_flow_backend.services.users import register_user, update_user

router = APIRouter()


@router.post(
    "",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_user(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db_session)],
) -> UserPublic:
    return UserPublic.model_validate(register_user(db, payload))


@router.get(
    "/me",
    response_model=UserPublic,
    responses={401: {"model": ErrorResponse}},
)
def read_current_user(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
) -> UserPublic:
    return UserPublic.model_validate(authenticated.user)


@router.patch(
    "/me",
    response_model=UserPublic,
    responses={
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def patch_current_user(
    payload: UserUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> UserPublic:
    return UserPublic.model_validate(update_user(db, authenticated.user, payload))


@router.get(
    "/me/profile",
    response_model=UserProfilePublic,
    responses={401: {"model": ErrorResponse}},
)
def read_current_profile(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> UserProfilePublic:
    profile = get_profile(db, authenticated.user.id)
    return UserProfilePublic.model_validate(profile)


@router.patch(
    "/me/profile",
    response_model=UserProfilePublic,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def patch_current_profile(
    payload: UserProfileUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> UserProfilePublic:
    profile = update_profile(db, authenticated.user.id, payload)
    return UserProfilePublic.model_validate(profile)
