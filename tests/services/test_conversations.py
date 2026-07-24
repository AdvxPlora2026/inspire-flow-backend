from collections.abc import Generator
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.errors import (
    ConversationArchivedError,
    ConversationBusyError,
    ConversationNotFoundError,
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
from inspire_flow_backend.schemas.conversations import (
    ConversationCreate,
    ConversationUpdate,
)
from inspire_flow_backend.schemas.memories import MemoryCategory
from inspire_flow_backend.services.conversations import (
    claim_conversation_run,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    release_conversation_run,
    update_conversation,
)
from inspire_flow_backend.services.memories import store_memory

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
    return ContextCipher.from_settings(
        Settings(
            _env_file=None,
            context_encryption_key=TEST_KEY,
            context_encryption_key_file=tmp_path / "unused.key",
        )
    )


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
    db.add(
        UserProfile(
            user=user,
            content_focus=[],
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    return user


def test_conversation_lifecycle_and_user_isolation(db: Session) -> None:
    owner = add_user(db, "aria")
    other = add_user(db, "beta")
    created = create_conversation(db, owner.id, ConversationCreate(title=" 新选题 "))

    assert created.title == "新选题"
    assert list_conversations(db, owner.id, include_archived=False, limit=20, offset=0).total == 1
    with pytest.raises(ConversationNotFoundError):
        get_conversation(db, other.id, created.id)

    archived = update_conversation(
        db,
        owner.id,
        created.id,
        ConversationUpdate(archived=True),
    )
    assert archived.archived is True
    assert (
        list_conversations(
            db,
            owner.id,
            include_archived=False,
            limit=20,
            offset=0,
        ).total
        == 0
    )
    restored = update_conversation(
        db,
        owner.id,
        created.id,
        ConversationUpdate(title=None, archived=False),
    )
    assert restored.title is None
    assert restored.archived is False


def test_delete_removes_unprotected_automatic_memories(
    db: Session,
    cipher: ContextCipher,
) -> None:
    owner = add_user(db, "aria")
    conversation = create_conversation(db, owner.id, ConversationCreate())
    memory = store_memory(
        db,
        user_id=owner.id,
        category=MemoryCategory.creative_focus,
        content="自动提取且未保护",
        origin="automatic",
        is_sensitive=False,
        cipher=cipher,
        source_conversation_id=conversation.id,
    )

    delete_conversation(db, owner.id, conversation.id)

    assert db.get(AgentConversation, conversation.id) is None
    assert db.get(UserMemory, memory.id) is None


def test_delete_keeps_explicit_edited_or_pinned_memories(
    db: Session,
    cipher: ContextCipher,
) -> None:
    owner = add_user(db, "aria")
    conversation = create_conversation(db, owner.id, ConversationCreate())
    explicit = store_memory(
        db,
        user_id=owner.id,
        category=MemoryCategory.other,
        content="用户明确要求保存",
        origin="explicit",
        is_sensitive=False,
        cipher=cipher,
        source_conversation_id=conversation.id,
    )
    edited = store_memory(
        db,
        user_id=owner.id,
        category=MemoryCategory.creative_focus,
        content="用户后来编辑过",
        origin="automatic",
        is_sensitive=False,
        cipher=cipher,
        source_conversation_id=conversation.id,
    )
    edited.user_edited = True
    pinned = store_memory(
        db,
        user_id=owner.id,
        category=MemoryCategory.workflow_preference,
        content="用户置顶过",
        origin="automatic",
        is_sensitive=False,
        cipher=cipher,
        is_pinned=True,
        source_conversation_id=conversation.id,
    )
    db.commit()

    delete_conversation(db, owner.id, conversation.id)

    assert {
        db.get(UserMemory, explicit.id).id,
        db.get(UserMemory, edited.id).id,
        db.get(UserMemory, pinned.id).id,
    } == {explicit.id, edited.id, pinned.id}


def test_surviving_memory_marks_source_deleted_without_message_content(
    db: Session,
    cipher: ContextCipher,
) -> None:
    owner = add_user(db, "aria")
    conversation = create_conversation(db, owner.id, ConversationCreate())
    message = AgentMessage(
        conversation_id=conversation.id,
        turn_id=uuid4(),
        sequence=1,
        item_type="message",
        role="user",
        payload_ciphertext=cipher.encrypt_json({"role": "user", "content": "删除后不可保留的原话"}),
        created_at=utc_now(),
    )
    conversation.next_sequence = 2
    db.add(message)
    db.commit()
    memory = store_memory(
        db,
        user_id=owner.id,
        category=MemoryCategory.other,
        content="明确保留的结论",
        origin="explicit",
        is_sensitive=False,
        cipher=cipher,
        source_conversation_id=conversation.id,
        source_message_id=message.id,
    )
    message_id = message.id

    delete_conversation(db, owner.id, conversation.id)
    db.expire_all()
    surviving = db.get(UserMemory, memory.id)

    assert surviving is not None
    assert surviving.source_conversation_id is None
    assert surviving.source_message_id is None
    assert surviving.source_deleted_at is not None
    assert db.get(AgentMessage, message_id) is None
    assert "删除后不可保留的原话" not in surviving.content_ciphertext


def test_second_live_run_cannot_claim_same_conversation(db: Session) -> None:
    owner = add_user(db, "aria")
    conversation = create_conversation(db, owner.id, ConversationCreate())
    first_run_id = uuid4()
    claim_conversation_run(
        db,
        user_id=owner.id,
        conversation_id=conversation.id,
        run_id=first_run_id,
        stale_before=utc_now() - timedelta(minutes=10),
    )

    with pytest.raises(ConversationBusyError):
        claim_conversation_run(
            db,
            user_id=owner.id,
            conversation_id=conversation.id,
            run_id=uuid4(),
            stale_before=utc_now() - timedelta(minutes=10),
        )

    release_conversation_run(
        db,
        user_id=owner.id,
        conversation_id=conversation.id,
        run_id=first_run_id,
    )


def test_stale_run_lock_can_be_reclaimed(db: Session) -> None:
    owner = add_user(db, "aria")
    conversation = create_conversation(db, owner.id, ConversationCreate())
    conversation.active_run_id = uuid4()
    conversation.active_run_started_at = utc_now() - timedelta(minutes=20)
    db.commit()
    replacement = uuid4()

    claimed = claim_conversation_run(
        db,
        user_id=owner.id,
        conversation_id=conversation.id,
        run_id=replacement,
        stale_before=utc_now() - timedelta(minutes=10),
    )

    assert claimed.active_run_id == replacement


def test_archived_conversation_rejects_run_claim(db: Session) -> None:
    owner = add_user(db, "aria")
    conversation = create_conversation(db, owner.id, ConversationCreate())
    update_conversation(
        db,
        owner.id,
        conversation.id,
        ConversationUpdate(archived=True),
    )

    with pytest.raises(ConversationArchivedError):
        claim_conversation_run(
            db,
            user_id=owner.id,
            conversation_id=conversation.id,
            run_id=uuid4(),
            stale_before=utc_now() - timedelta(minutes=10),
        )
