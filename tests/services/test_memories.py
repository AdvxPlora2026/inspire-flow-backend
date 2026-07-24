from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.errors import (
    CredentialMemoryForbiddenError,
    MemoryNotFoundError,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.database import create_database_engine
from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.data.models.auth_session import AuthSession
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.data.models.user_memory import UserMemory
from inspire_flow_backend.data.models.user_profile import UserProfile
from inspire_flow_backend.data.repositories.memories import list_active_memories_for_context
from inspire_flow_backend.schemas.memories import (
    MemoryCategory,
    MemoryStatus,
    UserMemoryCreate,
    UserMemoryUpdate,
)
from inspire_flow_backend.services.memories import (
    create_manual_memory,
    get_public_memory,
    store_memory,
    update_memory,
)

TEST_KEY = "79zUG7lNhJ1eTm2N-oWpgStPtMzGxJTgQ3wp8bVh3Y0="


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


@pytest.fixture
def cipher(tmp_path: Path) -> ContextCipher:
    settings = Settings(
        _env_file=None,
        context_encryption_key=TEST_KEY,
        context_encryption_key_file=tmp_path / "unused.key",
    )
    return ContextCipher.from_settings(settings)


def add_user(db: Session, nickname: str) -> User:
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
    return user


def test_manual_memory_is_encrypted_and_returned_to_owner(
    db: Session,
    cipher: ContextCipher,
) -> None:
    owner = add_user(db, "aria")
    content = "我偏好先写视频大纲"

    created = create_manual_memory(
        db,
        owner.id,
        UserMemoryCreate(
            category=MemoryCategory.workflow_preference,
            content=content,
            is_pinned=True,
        ),
        cipher,
    )
    raw = db.scalar(select(UserMemory).where(UserMemory.id == created.id))

    assert created.user_id == owner.id
    assert created.content == content
    assert created.origin == "manual"
    assert created.is_pinned is True
    assert raw is not None
    assert content not in raw.content_ciphertext
    assert cipher.decrypt_text(raw.content_ciphertext) == content


def test_credential_memory_is_rejected_before_persistence(
    db: Session,
    cipher: ContextCipher,
) -> None:
    owner = add_user(db, "aria")
    credential = "api_key=test-secret-placeholder"

    with pytest.raises(CredentialMemoryForbiddenError):
        create_manual_memory(
            db,
            owner.id,
            UserMemoryCreate(
                category=MemoryCategory.other,
                content=credential,
            ),
            cipher,
        )

    assert list(db.scalars(select(UserMemory))) == []


def test_foreign_memory_id_is_indistinguishable_from_unknown_id(
    db: Session,
    cipher: ContextCipher,
) -> None:
    owner = add_user(db, "aria")
    other = add_user(db, "beta")
    created = create_manual_memory(
        db,
        owner.id,
        UserMemoryCreate(
            category=MemoryCategory.creative_focus,
            content="科技内容",
        ),
        cipher,
    )

    with pytest.raises(MemoryNotFoundError):
        get_public_memory(db, other.id, created.id, cipher)
    with pytest.raises(MemoryNotFoundError):
        get_public_memory(db, other.id, uuid4(), cipher)


def test_edit_marks_automatic_memory_as_user_edited(
    db: Session,
    cipher: ContextCipher,
) -> None:
    owner = add_user(db, "aria")
    automatic = store_memory(
        db,
        user_id=owner.id,
        category=MemoryCategory.creative_focus,
        content="主要制作科技视频",
        origin="automatic",
        is_sensitive=False,
        cipher=cipher,
    )
    before = automatic.updated_at

    updated = update_memory(
        db,
        owner.id,
        automatic.id,
        UserMemoryUpdate(content="主要制作 AI 科技视频"),
        cipher,
    )

    assert updated.content == "主要制作 AI 科技视频"
    assert updated.user_edited is True
    assert updated.updated_at > before


def test_memory_no_op_preserves_timestamp_and_deduplicates(
    db: Session,
    cipher: ContextCipher,
) -> None:
    owner = add_user(db, "aria")
    payload = UserMemoryCreate(
        category=MemoryCategory.creative_focus,
        content="  科技 视频  ",
    )
    first = create_manual_memory(db, owner.id, payload, cipher)
    duplicate = create_manual_memory(
        db,
        owner.id,
        UserMemoryCreate(
            category=MemoryCategory.creative_focus,
            content="科技 视频",
        ),
        cipher,
    )
    unchanged = update_memory(
        db,
        owner.id,
        first.id,
        UserMemoryUpdate(status=MemoryStatus.active),
        cipher,
    )

    assert duplicate.id == first.id
    assert unchanged.updated_at == first.updated_at
    assert unchanged.user_edited is False
    assert len(list(db.scalars(select(UserMemory)))) == 1


def test_inactive_memory_is_excluded_from_context_query(
    db: Session,
    cipher: ContextCipher,
) -> None:
    owner = add_user(db, "aria")
    active = create_manual_memory(
        db,
        owner.id,
        UserMemoryCreate(
            category=MemoryCategory.creative_focus,
            content="活跃记忆",
            is_pinned=False,
        ),
        cipher,
    )
    pinned = create_manual_memory(
        db,
        owner.id,
        UserMemoryCreate(
            category=MemoryCategory.workflow_preference,
            content="置顶记忆",
            is_pinned=True,
        ),
        cipher,
    )
    inactive = create_manual_memory(
        db,
        owner.id,
        UserMemoryCreate(
            category=MemoryCategory.other,
            content="停用记忆",
            status=MemoryStatus.inactive,
        ),
        cipher,
    )

    selected = list_active_memories_for_context(db, owner.id, limit=10)

    assert [memory.id for memory in selected] == [pinned.id, active.id]
    assert inactive.id not in {memory.id for memory in selected}
