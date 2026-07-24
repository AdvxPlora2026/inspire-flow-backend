import asyncio
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
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
from inspire_flow_backend.services.agent.compaction import (
    CompactionInput,
    compact_conversation_if_needed,
)
from inspire_flow_backend.services.agent.context import AgentContextPolicy
from inspire_flow_backend.services.conversations import (
    claim_conversation_run,
    create_conversation,
)

TEST_KEY = "79zUG7lNhJ1eTm2N-oWpgStPtMzGxJTgQ3wp8bVh3Y0="


@dataclass
class FakeCompactor:
    result: str
    calls: list[CompactionInput] = field(default_factory=list)
    error: Exception | None = None

    async def compact(self, value: CompactionInput) -> str:
        self.calls.append(value)
        if self.error is not None:
            raise self.error
        return self.result


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


@pytest.fixture
def policy() -> AgentContextPolicy:
    return AgentContextPolicy(
        trigger_characters=40,
        max_characters=1000,
        recent_turns=1,
        summary_max_characters=200,
        memory_max_items=10,
        memory_max_characters=200,
    )


def make_conversation(db: Session) -> tuple[User, AgentConversation, UUID]:
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
    return user, conversation, run_id


def append_turn(
    db: Session,
    conversation: AgentConversation,
    cipher: ContextCipher,
    label: str,
) -> None:
    turn_id = uuid4()
    first_sequence = conversation.next_sequence
    now = utc_now()
    db.add_all(
        [
            AgentMessage(
                conversation_id=conversation.id,
                turn_id=turn_id,
                sequence=first_sequence,
                item_type="message",
                role="user",
                payload_ciphertext=cipher.encrypt_json(
                    {"role": "user", "content": f"{label} 用户内容"}
                ),
                created_at=now,
            ),
            AgentMessage(
                conversation_id=conversation.id,
                turn_id=turn_id,
                sequence=first_sequence + 1,
                item_type="message",
                role="assistant",
                payload_ciphertext=cipher.encrypt_json(
                    {"role": "assistant", "content": f"{label} 助手回复"}
                ),
                created_at=now,
            ),
        ]
    )
    conversation.next_sequence += 2
    db.commit()


def compact(
    db: Session,
    user: User,
    conversation: AgentConversation,
    run_id: UUID,
    cipher: ContextCipher,
    policy: AgentContextPolicy,
    compactor: FakeCompactor,
):
    return asyncio.run(
        compact_conversation_if_needed(
            db,
            user_id=user.id,
            conversation_id=conversation.id,
            run_id=run_id,
            cipher=cipher,
            policy=policy,
            compactor=compactor,
        )
    )


def test_compaction_below_threshold_is_no_op(
    db: Session,
    cipher: ContextCipher,
    policy: AgentContextPolicy,
) -> None:
    user, conversation, run_id = make_conversation(db)
    append_turn(db, conversation, cipher, "短")
    compactor = FakeCompactor("不应调用")
    high_threshold = AgentContextPolicy(
        trigger_characters=10_000,
        max_characters=policy.max_characters,
        recent_turns=policy.recent_turns,
        summary_max_characters=policy.summary_max_characters,
        memory_max_items=policy.memory_max_items,
        memory_max_characters=policy.memory_max_characters,
    )

    outcome = compact(
        db,
        user,
        conversation,
        run_id,
        cipher,
        high_threshold,
        compactor,
    )

    assert outcome.status == "skipped"
    assert compactor.calls == []
    assert conversation.summary_through_sequence == 0


def test_compaction_advances_cursor_repeatedly_and_preserves_raw_rows(
    db: Session,
    cipher: ContextCipher,
    policy: AgentContextPolicy,
) -> None:
    user, conversation, run_id = make_conversation(db)
    for label in ("第一轮", "第二轮", "第三轮"):
        append_turn(db, conversation, cipher, label)
    first_compactor = FakeCompactor("第一版摘要")

    first = compact(
        db,
        user,
        conversation,
        run_id,
        cipher,
        policy,
        first_compactor,
    )

    assert first.status == "compacted"
    assert conversation.summary_through_sequence == 4
    assert cipher.decrypt_text(conversation.summary_ciphertext) == "第一版摘要"
    assert "第三轮" not in str(first_compactor.calls[0].items)
    for label in ("第四轮", "第五轮"):
        append_turn(db, conversation, cipher, label)
    second_compactor = FakeCompactor("第二版摘要")

    second = compact(
        db,
        user,
        conversation,
        run_id,
        cipher,
        policy,
        second_compactor,
    )

    assert second.status == "compacted"
    assert conversation.summary_through_sequence == 8
    assert second_compactor.calls[0].previous_summary == "第一版摘要"
    assert (
        db.scalar(
            select(func.count())
            .select_from(AgentMessage)
            .where(AgentMessage.conversation_id == conversation.id)
        )
        == 10
    )


@pytest.mark.parametrize(
    "compactor",
    [
        FakeCompactor(""),
        FakeCompactor("x" * 201),
        FakeCompactor("", error=RuntimeError("model failed")),
    ],
)
def test_invalid_or_failed_compaction_keeps_previous_state(
    db: Session,
    cipher: ContextCipher,
    policy: AgentContextPolicy,
    compactor: FakeCompactor,
) -> None:
    user, conversation, run_id = make_conversation(db)
    for label in ("第一轮", "第二轮"):
        append_turn(db, conversation, cipher, label)

    outcome = compact(
        db,
        user,
        conversation,
        run_id,
        cipher,
        policy,
        compactor,
    )

    assert outcome.status == "failed"
    assert conversation.summary_ciphertext is None
    assert conversation.summary_through_sequence == 0


def test_optimistic_cursor_mismatch_does_not_overwrite_summary(
    db: Session,
    cipher: ContextCipher,
    policy: AgentContextPolicy,
) -> None:
    user, conversation, run_id = make_conversation(db)
    for label in ("第一轮", "第二轮"):
        append_turn(db, conversation, cipher, label)

    class CursorChangingCompactor:
        async def compact(self, value: CompactionInput) -> str:
            del value
            conversation.summary_through_sequence = 1
            conversation.summary_ciphertext = cipher.encrypt_text("并发摘要")
            db.commit()
            return "不应覆盖"

    outcome = asyncio.run(
        compact_conversation_if_needed(
            db,
            user_id=user.id,
            conversation_id=conversation.id,
            run_id=run_id,
            cipher=cipher,
            policy=policy,
            compactor=CursorChangingCompactor(),
        )
    )

    assert outcome.status == "stale"
    assert conversation.summary_through_sequence == 1
    assert cipher.decrypt_text(conversation.summary_ciphertext) == "并发摘要"
