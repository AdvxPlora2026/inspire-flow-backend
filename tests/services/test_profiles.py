from collections.abc import Generator
from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.database import create_database_engine
from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.data.models.auth_session import AuthSession
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.data.models.user_memory import UserMemory
from inspire_flow_backend.data.models.user_profile import UserProfile
from inspire_flow_backend.schemas.profiles import UserProfileUpdate
from inspire_flow_backend.services.profiles import get_profile, update_profile


@pytest.fixture
def db() -> Generator[Session]:
    engine = create_database_engine("sqlite://")
    assert {
        AgentConversation.__tablename__,
        AgentMessage.__tablename__,
        AuthSession.__tablename__,
        User.__tablename__,
        UserMemory.__tablename__,
        UserProfile.__tablename__,
    } <= set(Base.metadata.tables)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def add_user_with_profile(db: Session, nickname: str) -> tuple[User, UserProfile]:
    now = utc_now()
    user = User(
        id=uuid4(),
        nickname=nickname,
        nickname_key=nickname.casefold(),
        password_hash="test-only-hash",
        created_at=now,
        updated_at=now,
    )
    profile = UserProfile(
        user=user,
        content_focus=[],
        created_at=now,
        updated_at=now,
    )
    db.add_all((user, profile))
    db.commit()
    return user, profile


def test_profile_update_normalizes_values_and_preserves_owner(db: Session) -> None:
    owner, profile = add_user_with_profile(db, "aria")
    other, _ = add_user_with_profile(db, "beta")
    before = profile.updated_at

    result = update_profile(
        db,
        owner.id,
        UserProfileUpdate(
            bio="  记录有用的创作过程  ",
            timezone="Asia/Shanghai",
            preferred_language="  zh-CN ",
            creator_identity=" 科技区 UP 主 ",
            content_focus=[" AI ", "数码", "ai", "  "],
            collaboration_preferences="  先文字沟通  ",
        ),
    )

    assert result.user_id == owner.id
    assert result.bio == "记录有用的创作过程"
    assert result.timezone == "Asia/Shanghai"
    assert result.preferred_language == "zh-CN"
    assert result.creator_identity == "科技区 UP 主"
    assert result.content_focus == ["AI", "数码"]
    assert result.collaboration_preferences == "先文字沟通"
    assert result.updated_at > before
    assert get_profile(db, other.id).user_id == other.id
    assert get_profile(db, other.id).content_focus == []


def test_profile_nullable_values_can_be_cleared(db: Session) -> None:
    owner, profile = add_user_with_profile(db, "aria")
    profile.bio = "old"
    profile.timezone = "UTC"
    db.commit()

    result = update_profile(
        db,
        owner.id,
        UserProfileUpdate(bio=None, timezone=None),
    )

    assert result.bio is None
    assert result.timezone is None


def test_profile_no_op_preserves_updated_at(db: Session) -> None:
    owner, profile = add_user_with_profile(db, "aria")
    profile.preferred_language = "zh-CN"
    db.commit()
    before = profile.updated_at

    result = update_profile(
        db,
        owner.id,
        UserProfileUpdate(preferred_language=" zh-CN "),
    )

    assert result.updated_at == before
    assert result.updated_at <= utc_now() + timedelta(seconds=1)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"timezone": "Mars/Olympus"},
        {"preferred_language": "   "},
        {"creator_identity": ""},
        {"unknown": "must not leak"},
    ],
)
def test_profile_update_rejects_invalid_payload(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        UserProfileUpdate.model_validate(payload)
