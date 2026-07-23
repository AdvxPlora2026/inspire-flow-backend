from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import InvalidSessionError
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.services.sessions import (
    AuthenticatedSession,
    resolve_session,
)

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_session(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: Annotated[Session, Depends(get_db_session)],
) -> AuthenticatedSession:
    if (
        credentials is None
        or credentials.scheme.casefold() != "bearer"
        or not credentials.credentials
    ):
        raise InvalidSessionError
    return resolve_session(db, credentials.credentials)
