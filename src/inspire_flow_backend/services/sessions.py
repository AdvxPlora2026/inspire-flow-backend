from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import (
    InvalidCredentialsError,
    InvalidSessionError,
)
from inspire_flow_backend.core.identity import nickname_key
from inspire_flow_backend.core.security import (
    DUMMY_PASSWORD_HASH,
    digest_session_token,
    generate_session_token,
    verify_password,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.auth_session import AuthSession
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.data.repositories.sessions import (
    add_session,
    delete_session,
    get_session_by_token_hash,
)
from inspire_flow_backend.data.repositories.users import get_user_by_nickname_key
from inspire_flow_backend.schemas.sessions import SessionCreate


@dataclass(frozen=True, slots=True)
class CreatedSession:
    access_token: str
    expires_at: datetime
    user: User


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    session: AuthSession
    user: User


def create_session(
    db: Session,
    payload: SessionCreate,
    ttl_hours: int,
) -> CreatedSession:
    user = get_user_by_nickname_key(db, nickname_key(payload.nickname))
    password_hash_value = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_is_valid = verify_password(
        payload.password.get_secret_value(),
        password_hash_value,
    )
    if user is None or not password_is_valid:
        raise InvalidCredentialsError

    now = utc_now()
    access_token = generate_session_token()
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=digest_session_token(access_token),
        expires_at=now + timedelta(hours=ttl_hours),
        created_at=now,
    )
    add_session(db, auth_session)
    db.commit()
    db.refresh(auth_session)
    return CreatedSession(
        access_token=access_token,
        expires_at=auth_session.expires_at,
        user=user,
    )


def resolve_session(db: Session, token: str) -> AuthenticatedSession:
    auth_session = get_session_by_token_hash(
        db,
        digest_session_token(token),
    )
    if auth_session is None:
        raise InvalidSessionError
    if auth_session.expires_at <= utc_now():
        delete_session(db, auth_session)
        db.commit()
        raise InvalidSessionError
    return AuthenticatedSession(
        session=auth_session,
        user=auth_session.user,
    )


def revoke_session(db: Session, auth_session: AuthSession) -> None:
    delete_session(db, auth_session)
    db.commit()
