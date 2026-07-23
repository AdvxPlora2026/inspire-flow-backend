from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import NicknameConflictError
from inspire_flow_backend.core.identity import nickname_key
from inspire_flow_backend.core.security import hash_password
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.data.repositories.users import add_user
from inspire_flow_backend.schemas.users import UserCreate, UserUpdate


def register_user(db: Session, payload: UserCreate) -> User:
    now = utc_now()
    user = User(
        nickname=payload.nickname,
        nickname_key=nickname_key(payload.nickname),
        avatar_url=str(payload.avatar_url) if payload.avatar_url is not None else None,
        password_hash=hash_password(payload.password.get_secret_value()),
        created_at=now,
        updated_at=now,
    )
    add_user(db, user)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise NicknameConflictError from error
    db.refresh(user)
    return user


def update_user(db: Session, user: User, payload: UserUpdate) -> User:
    changed = False
    if "nickname" in payload.model_fields_set:
        assert payload.nickname is not None
        new_nickname_key = nickname_key(payload.nickname)
        if user.nickname != payload.nickname or user.nickname_key != new_nickname_key:
            user.nickname = payload.nickname
            user.nickname_key = new_nickname_key
            changed = True

    if "avatar_url" in payload.model_fields_set:
        new_avatar_url = str(payload.avatar_url) if payload.avatar_url is not None else None
        if user.avatar_url != new_avatar_url:
            user.avatar_url = new_avatar_url
            changed = True

    if not changed:
        return user

    user.updated_at = utc_now()
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise NicknameConflictError from error
    db.refresh(user)
    return user
