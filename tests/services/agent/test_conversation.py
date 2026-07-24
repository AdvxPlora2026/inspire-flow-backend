import asyncio
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest
from agents import ModelBehaviorError, RunConfig, Session, TResponseInputItem
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DatabaseSession
from sqlalchemy.orm import sessionmaker

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.errors import (
    AgentRunFailedError,
    ConversationArchivedError,
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
from inspire_flow_backend.services.agent.compaction import CompactionInput
from inspire_flow_backend.services.agent.context import ContextInputFilter
from inspire_flow_backend.services.agent.conversation import run_conversation_turn
from inspire_flow_backend.services.agent.memory_extraction import (
    AcceptedMemoryCandidate,
    MemoryExtractionResult,
)
from inspire_flow_backend.services.agent.runtime import AgentRuntime
from inspire_flow_backend.services.conversations import (
    create_conversation,
    update_conversation,
)

TEST_KEY = "79zUG7lNhJ1eTm2N-oWpgStPtMzGxJTgQ3wp8bVh3Y0="


@dataclass
class FakeConversationAgent:
    events: list[str]
    fail: bool = False
    calls: list[tuple[object, RunConfig]] = field(default_factory=list)
    seen_history: list[TResponseInputItem] = field(default_factory=list)

    async def run(
        self,
        input: str | list[TResponseInputItem],
        *,
        max_turns: int | None = None,
        session: Session | None = None,
        run_config: RunConfig | None = None,
    ) -> object:
        del max_turns
        assert input == []
        assert session is not None
        assert run_config is not None
        self.events.append("agent")
        self.calls.append((session, run_config))
        self.seen_history = await session.get_items()
        if self.fail:
            raise ModelBehaviorError("test model failure")
        await session.add_items(
            [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "先从目标受众开始。",
                        }
                    ],
                }
            ]
        )
        return object()

    async def aclose(self) -> None:
        return None


@dataclass
class FakeCompactor:
    events: list[str]
    result: str = "旧对话摘要"
    error: Exception | None = None
    calls: list[CompactionInput] = field(default_factory=list)

    async def compact(self, value: CompactionInput) -> str:
        self.events.append("compactor")
        self.calls.append(value)
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class FakeExtractor:
    events: list[str]
    result: MemoryExtractionResult
    messages: list[str] = field(default_factory=list)

    async def extract(self, user_message: str) -> MemoryExtractionResult:
        self.events.append("extractor")
        self.messages.append(user_message)
        return self.result


@pytest.fixture
def db() -> Generator[DatabaseSession]:
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
def settings() -> Settings:
    return Settings(
        _env_file=None,
        agent_context_trigger_characters=1,
        agent_context_max_characters=1000,
        agent_context_recent_turns=1,
        agent_context_summary_max_characters=200,
        agent_memory_max_items=10,
        agent_memory_max_characters=200,
        agent_run_lock_ttl_seconds=600,
    )


def add_user(db: DatabaseSession, nickname: str) -> User:
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
            content_focus=["科技"],
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    return user


def seed_two_turns(
    db: DatabaseSession,
    conversation: AgentConversation,
    cipher: ContextCipher,
) -> None:
    now = utc_now()
    messages: list[AgentMessage] = []
    for turn_index in range(2):
        turn_id = uuid4()
        for role in ("user", "assistant"):
            sequence = len(messages) + 1
            messages.append(
                AgentMessage(
                    conversation_id=conversation.id,
                    turn_id=turn_id,
                    sequence=sequence,
                    item_type="message",
                    role=role,
                    payload_ciphertext=cipher.encrypt_json(
                        {"role": role, "content": f"旧轮次 {turn_index} {role}"}
                    ),
                    created_at=now,
                )
            )
    conversation.next_sequence = 5
    db.add_all(messages)
    db.commit()


def make_runtime(
    *,
    events: list[str],
    extraction: MemoryExtractionResult,
    fail_agent: bool = False,
    compaction_error: Exception | None = None,
) -> AgentRuntime:
    return AgentRuntime(
        conversation_agent=FakeConversationAgent(events, fail=fail_agent),
        compactor=FakeCompactor(events, error=compaction_error),
        memory_extractor=FakeExtractor(events, extraction),
    )


def test_turn_orders_compaction_persistence_agent_extraction_and_unlock(
    db: DatabaseSession,
    cipher: ContextCipher,
    settings: Settings,
) -> None:
    user = add_user(db, "aria")
    conversation = create_conversation(db, user.id, ConversationCreate())
    seed_two_turns(db, conversation, cipher)
    events: list[str] = []
    extraction = MemoryExtractionResult(
        status="completed",
        candidates=(
            AcceptedMemoryCandidate(
                category=MemoryCategory.creative_focus,
                content="用户主要制作科技视频",
                evidence="我主要做科技视频",
                is_sensitive=False,
                origin="automatic",
            ),
        ),
    )
    runtime = make_runtime(events=events, extraction=extraction)

    result = asyncio.run(
        run_conversation_turn(
            db,
            user=user,
            conversation_id=conversation.id,
            content="我主要做科技视频 token=top-secret-value",
            runtime=runtime,
            cipher=cipher,
            settings=settings,
        )
    )

    assert events == ["compactor", "agent", "extractor"]
    agent = runtime.conversation_agent
    assert isinstance(agent, FakeConversationAgent)
    assert agent.calls[0][1].trace_include_sensitive_data is False
    assert isinstance(agent.calls[0][1].call_model_input_filter, ContextInputFilter)
    assert "top-secret-value" not in str(agent.seen_history)
    assert "[REDACTED_CREDENTIAL]" in str(agent.seen_history)
    assert result.user_message.content.endswith("[REDACTED_CREDENTIAL]")
    assert result.assistant_message.content == "先从目标受众开始。"
    assert result.memory_extraction_status == "completed"
    assert [memory.content for memory in result.memory_updates] == ["用户主要制作科技视频"]
    assert conversation.active_run_id is None
    assert conversation.title == "我主要做科技视频 token=[REDACTED_CREDENTIAL]"


def test_model_failure_preserves_user_message_and_releases_lock(
    db: DatabaseSession,
    cipher: ContextCipher,
    settings: Settings,
) -> None:
    user = add_user(db, "aria")
    conversation = create_conversation(db, user.id, ConversationCreate())
    runtime = make_runtime(
        events=[],
        extraction=MemoryExtractionResult(status="completed", candidates=()),
        fail_agent=True,
    )

    with pytest.raises(AgentRunFailedError):
        asyncio.run(
            run_conversation_turn(
                db,
                user=user,
                conversation_id=conversation.id,
                content="保留这条用户输入",
                runtime=runtime,
                cipher=cipher,
                settings=settings,
            )
        )

    db.refresh(conversation)
    assert conversation.active_run_id is None
    rows = list(
        db.scalars(select(AgentMessage).where(AgentMessage.conversation_id == conversation.id))
    )
    assert len(rows) == 1
    assert cipher.decrypt_json(rows[0].payload_ciphertext)["content"] == "保留这条用户输入"


def test_compaction_and_extraction_failure_do_not_discard_reply(
    db: DatabaseSession,
    cipher: ContextCipher,
    settings: Settings,
) -> None:
    user = add_user(db, "aria")
    conversation = create_conversation(db, user.id, ConversationCreate())
    seed_two_turns(db, conversation, cipher)
    runtime = make_runtime(
        events=[],
        extraction=MemoryExtractionResult(status="failed", candidates=()),
        compaction_error=RuntimeError("summary unavailable"),
    )

    result = asyncio.run(
        run_conversation_turn(
            db,
            user=user,
            conversation_id=conversation.id,
            content="继续推进",
            runtime=runtime,
            cipher=cipher,
            settings=settings,
        )
    )

    assert result.assistant_message.content == "先从目标受众开始。"
    assert result.memory_extraction_status == "failed"
    assert result.memory_updates == ()
    assert conversation.active_run_id is None


def test_turn_rejects_archived_and_foreign_conversations(
    db: DatabaseSession,
    cipher: ContextCipher,
    settings: Settings,
) -> None:
    owner = add_user(db, "aria")
    other = add_user(db, "beta")
    conversation = create_conversation(db, owner.id, ConversationCreate())
    update_conversation(
        db,
        owner.id,
        conversation.id,
        ConversationUpdate(archived=True),
    )
    runtime = make_runtime(
        events=[],
        extraction=MemoryExtractionResult(status="completed", candidates=()),
    )

    with pytest.raises(ConversationArchivedError):
        asyncio.run(
            run_conversation_turn(
                db,
                user=owner,
                conversation_id=conversation.id,
                content="继续",
                runtime=runtime,
                cipher=cipher,
                settings=settings,
            )
        )
    with pytest.raises(ConversationNotFoundError):
        asyncio.run(
            run_conversation_turn(
                db,
                user=other,
                conversation_id=conversation.id,
                content="越权",
                runtime=runtime,
                cipher=cipher,
                settings=settings,
            )
        )

    assert (
        db.scalar(
            select(func.count())
            .select_from(AgentMessage)
            .where(AgentMessage.conversation_id == conversation.id)
        )
        == 0
    )
