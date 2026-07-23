from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import get_current_session
from inspire_flow_backend.core.config import Settings, get_settings
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.errors import ErrorResponse
from inspire_flow_backend.schemas.sessions import SessionCreate, SessionCreated
from inspire_flow_backend.schemas.users import UserPublic
from inspire_flow_backend.services.sessions import (
    AuthenticatedSession,
    create_session,
    revoke_session,
)

router = APIRouter()


@router.post(
    "",
    response_model=SessionCreated,
    status_code=status.HTTP_201_CREATED,
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def login(
    payload: SessionCreate,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionCreated:
    created = create_session(db, payload, settings.session_ttl_hours)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return SessionCreated(
        access_token=created.access_token,
        expires_at=created.expires_at,
        user=UserPublic.model_validate(created.user),
    )


@router.delete(
    "/current",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ErrorResponse}},
)
def logout(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    revoke_session(db, authenticated.session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
