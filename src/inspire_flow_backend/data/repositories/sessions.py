from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from inspire_flow_backend.data.models.auth_session import AuthSession


def add_session(db: Session, auth_session: AuthSession) -> None:
    db.add(auth_session)


def get_session_by_token_hash(db: Session, token_hash: str) -> AuthSession | None:
    statement = (
        select(AuthSession)
        .options(joinedload(AuthSession.user))
        .where(AuthSession.token_hash == token_hash)
    )
    return db.scalar(statement)


def delete_session(db: Session, auth_session: AuthSession) -> None:
    db.delete(auth_session)
