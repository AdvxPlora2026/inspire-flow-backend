from sqlalchemy import select
from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.user import User


def get_user_by_nickname_key(db: Session, key: str) -> User | None:
    return db.scalar(select(User).where(User.nickname_key == key))


def add_user(db: Session, user: User) -> None:
    db.add(user)
