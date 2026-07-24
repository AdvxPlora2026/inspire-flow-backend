import asyncio
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.database import create_database_engine
from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.data.models.auth_session import AuthSession
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.data.models.user_memory import UserMemory
from inspire_flow_backend.data.models.user_profile import UserProfile
from inspire_flow_backend.schemas.conversations import ConversationCreate
from inspire_flow_backend.services.agent.session import (
    ConversationSessionStateError,
    DatabaseAgentSession,
)
from inspire_flow_backend.services.conversations import (
    claim_conversation_run,
    create_conversation,
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
    return ContextCipher.from_settings(
        Settings(
            _env_file=None,
            context_encryption_key=TEST_KEY,
            context_encryption_key_file=tmp_path / "unused.key",
        )
    )


def make_session(
    db: Session,
    cipher: ContextCipher,
) -> tuple[DatabaseAgentSession, User, AgentConversation]:
    now = utc_now()
    user = User(
        id=uuid4(),
        nickname="aria",
        nickname_key="aria",
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
    conversation = create_conversation(db, user.id, ConversationCreate())
    run_id = uuid4()
    claim_conversation_run(
        db,
        user_id=user.id,
        conversation_id=conversation.id,
        run_id=run_id,
        stale_before=now,
    )
    adapter = DatabaseAgentSession(
        db=db,
        user_id=user.id,
        conversation_id=conversation.id,
        turn_id=uuid4(),
        run_id=run_id,
        cipher=cipher,
    )
    return adapter, user, conversation


def representative_items() -> list[dict[str, object]]:
    return [
        {"role": "user", "content": "做一期 AI 视频"},
        {
            "type": "function_call",
            "call_id": "call-1",
            "name": "search_website",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": "token=top-secret-value 搜索结果",
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "先确定受众。"}],
        },
    ]


def test_session_appends_encrypted_items_with_monotonic_sequences(
    db: Session,
    cipher: ContextCipher,
) -> None:
    adapter, _, conversation = make_session(db, cipher)
    items = representative_items()

    asyncio.run(adapter.add_items(items[:2]))
    asyncio.run(adapter.add_items(items[2:]))
    persisted = list(
        db.scalars(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation.id)
            .order_by(AgentMessage.sequence)
        )
    )
    restored = asyncio.run(adapter.get_items())

    assert [message.sequence for message in persisted] == [1, 2, 3, 4]
    assert conversation.next_sequence == 5
    assert "做一期 AI 视频" not in persisted[0].payload_ciphertext
    assert "top-secret-value" not in persisted[2].payload_ciphertext
    assert restored[0] == items[0]
    assert restored[2]["output"] == "token=[REDACTED_CREDENTIAL] 搜索结果"
    assert restored[3] == items[3]


def test_session_get_items_returns_only_persisted_items_after_summary_cursor(
    db: Session,
    cipher: ContextCipher,
) -> None:
    adapter, _, conversation = make_session(db, cipher)
    items = representative_items()
    asyncio.run(adapter.add_items(items))
    conversation.summary_through_sequence = 2
    db.commit()

    restored = asyncio.run(adapter.get_items())

    assert restored == [
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": "token=[REDACTED_CREDENTIAL] 搜索结果",
        },
        items[3],
    ]


def test_session_limit_returns_at_most_latest_items_in_order(
    db: Session,
    cipher: ContextCipher,
) -> None:
    adapter, _, _ = make_session(db, cipher)
    items = representative_items()
    asyncio.run(adapter.add_items(items))

    restored = asyncio.run(adapter.get_items(limit=2))

    assert [item["type"] for item in restored] == [
        "function_call_output",
        "message",
    ]
    assert asyncio.run(adapter.get_items(limit=0)) == []


def test_session_rejects_foreign_user_and_wrong_run_id(
    db: Session,
    cipher: ContextCipher,
) -> None:
    adapter, _, conversation = make_session(db, cipher)
    foreign = DatabaseAgentSession(
        db=db,
        user_id=uuid4(),
        conversation_id=conversation.id,
        turn_id=uuid4(),
        run_id=adapter.run_id,
        cipher=cipher,
    )
    wrong_run = DatabaseAgentSession(
        db=db,
        user_id=adapter.user_id,
        conversation_id=conversation.id,
        turn_id=uuid4(),
        run_id=uuid4(),
        cipher=cipher,
    )

    with pytest.raises(ConversationSessionStateError):
        asyncio.run(foreign.get_items())
    with pytest.raises(ConversationSessionStateError):
        asyncio.run(wrong_run.add_items([{"role": "user", "content": "x"}]))


def test_session_pop_and_clear_update_conversation_state(
    db: Session,
    cipher: ContextCipher,
) -> None:
    adapter, _, conversation = make_session(db, cipher)
    items = representative_items()
    asyncio.run(adapter.add_items(items))

    popped = asyncio.run(adapter.pop_item())

    assert popped == items[-1]
    assert conversation.next_sequence == 4
    assert len(asyncio.run(adapter.get_items())) == 3

    asyncio.run(adapter.clear_session())

    assert asyncio.run(adapter.get_items()) == []
    assert conversation.next_sequence == 1
    assert conversation.summary_through_sequence == 0
    assert conversation.summary_ciphertext is None
