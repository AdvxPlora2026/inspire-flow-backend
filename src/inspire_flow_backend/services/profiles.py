from uuid import UUID

from sqlalchemy.orm import Session

from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.user_profile import UserProfile
from inspire_flow_backend.data.repositories.profiles import get_profile_by_user_id
from inspire_flow_backend.schemas.profiles import UserProfileUpdate


def get_profile(db: Session, user_id: UUID) -> UserProfile:
    profile = get_profile_by_user_id(db, user_id)
    if profile is None:
        raise RuntimeError("Authenticated user profile is missing")
    return profile


def update_profile(
    db: Session,
    user_id: UUID,
    payload: UserProfileUpdate,
) -> UserProfile:
    profile = get_profile(db, user_id)
    changed = False

    for field_name in payload.model_fields_set:
        new_value = getattr(payload, field_name)
        if getattr(profile, field_name) != new_value:
            setattr(profile, field_name, new_value)
            changed = True

    if not changed:
        return profile

    profile.updated_at = utc_now()
    db.commit()
    db.refresh(profile)
    return profile
