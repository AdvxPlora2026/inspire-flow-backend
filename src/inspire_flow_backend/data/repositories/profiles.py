from uuid import UUID

from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.user_profile import UserProfile


def get_profile_by_user_id(db: Session, user_id: UUID) -> UserProfile | None:
    return db.get(UserProfile, user_id)


def add_profile(db: Session, profile: UserProfile) -> None:
    db.add(profile)
