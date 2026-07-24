import asyncio
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from agents import Agent
from agents.run_config import CallModelData, ModelInputData
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.errors import ConversationNotFoundError
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
from inspire_flow_backend.schemas.memories import MemoryCategory
from inspire_flow_backend.services.agent.context import (
    AgentContextPolicy,
    ContextInputFilter,
    build_dynamic_context,
)
from inspire_flow_backend.services.conversations import create_conversation
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


def add_user(db: Session, nickname: str, focus: str) -> User:
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
            bio=f"{nickname} 的资料",
            timezone="Asia/Shanghai",
            preferred_language="zh-CN",
            creator_identity="B站 UP 主",
            content_focus=[focus],
            collaboration_preferences="先确认大纲",
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    return user


def test_context_filter_is_user_scoped_bounded_and_ordered(
    db: Session,
    cipher: ContextCipher,
) -> None:
    owner = add_user(db, "aria", "科技")
    owner.profile_text = "偏好做有实测数据的科技视频"
    foreign = add_user(db, "beta", "美食")
    conversation = create_conversation(db, owner.id, ConversationCreate())
    conversation.summary_ciphertext = cipher.encrypt_text("已确认做一期本地模型视频")
    db.commit()
    store_memory(
        db,
        user_id=owner.id,
        category=MemoryCategory.creative_focus,
        content="近期关注开源 AI",
        origin="automatic",
        is_sensitive=False,
        cipher=cipher,
    )
    store_memory(
        db,
        user_id=owner.id,
        category=MemoryCategory.workflow_preference,
        content="先给三个标题方向",
        origin="explicit",
        is_sensitive=True,
        is_pinned=True,
        cipher=cipher,
    )
    store_memory(
        db,
        user_id=owner.id,
        category=MemoryCategory.other,
        content="不应进入上下文",
        origin="manual",
        is_sensitive=False,
        status="inactive",
        cipher=cipher,
    )
    store_memory(
        db,
        user_id=foreign.id,
        category=MemoryCategory.other,
        content="其他用户的秘密",
        origin="manual",
        is_sensitive=True,
        cipher=cipher,
    )
    policy = AgentContextPolicy(
        trigger_characters=500,
        max_characters=1200,
        recent_turns=2,
        summary_max_characters=200,
        memory_max_items=10,
        memory_max_characters=300,
    )
    dynamic = build_dynamic_context(
        db,
        user=owner,
        conversation=conversation,
        cipher=cipher,
        policy=policy,
    )
    context_filter = ContextInputFilter(dynamic, policy=policy)
    model_input = ModelInputData(
        input=[
            {"role": "user", "content": "最旧轮次"},
            {"role": "assistant", "content": "旧回复"},
            {"role": "user", "content": "保留轮次"},
            {"role": "assistant", "content": "保留回复"},
            {"role": "user", "content": "当前轮次"},
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "x" * 2000,
            },
            {"role": "assistant", "content": "当前回复"},
        ],
        instructions="base",
    )
    call_data = CallModelData(
        model_data=model_input,
        agent=Agent(name="test", instructions="test"),
        context=None,
    )

    filtered = asyncio.run(context_filter(call_data))
    system_text = filtered.input[0]["content"]

    assert isinstance(system_text, str)
    assert system_text.index("用户资料") < system_text.index("长期记忆")
    assert system_text.index("长期记忆") < system_text.index("对话摘要")
    assert "科技" in system_text
    assert "偏好做有实测数据的科技视频" in system_text
    assert "先给三个标题方向" in system_text
    assert "近期关注开源 AI" in system_text
    assert system_text.index("先给三个标题方向") < system_text.index("近期关注开源 AI")
    assert "敏感" in system_text
    assert "已确认做一期本地模型视频" in system_text
    assert "不应进入上下文" not in system_text
    assert "其他用户的秘密" not in system_text
    assert "最旧轮次" not in str(filtered.input)
    assert "保留轮次" in str(filtered.input)
    assert "当前轮次" in str(filtered.input)
    assert "TRUNCATED" in str(filtered.input)
    assert filtered.instructions == "base"
    assert sum(len(str(item)) for item in filtered.input) <= policy.max_characters
    assert (
        db.scalar(
            select(func.count())
            .select_from(AgentMessage)
            .where(AgentMessage.conversation_id == conversation.id)
        )
        == 0
    )


def test_dynamic_context_rejects_foreign_conversation(
    db: Session,
    cipher: ContextCipher,
) -> None:
    owner = add_user(db, "aria", "科技")
    foreign = add_user(db, "beta", "美食")
    conversation = create_conversation(db, owner.id, ConversationCreate())
    policy = AgentContextPolicy(
        trigger_characters=500,
        max_characters=1200,
        recent_turns=2,
        summary_max_characters=200,
        memory_max_items=10,
        memory_max_characters=300,
    )

    with pytest.raises(ConversationNotFoundError):
        build_dynamic_context(
            db,
            user=foreign,
            conversation=conversation,
            cipher=cipher,
            policy=policy,
        )
