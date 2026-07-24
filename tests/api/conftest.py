from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from agents import Agent, ModelBehaviorError
from agents.run_config import CallModelData, ModelInputData
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.api.dependencies import (
    get_agent_runtime,
    get_agent_stream_runtime_factory,
    get_context_cipher,
    get_injective_provider,
)
from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.database import (
    create_database_engine,
    get_db_session,
)
from inspire_flow_backend.data.model_registry import register_models
from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.data.models.auth_session import AuthSession
from inspire_flow_backend.data.models.inspiration import Inspiration
from inspire_flow_backend.data.models.project import Project
from inspire_flow_backend.data.models.transcription_job import TranscriptionJob
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.data.models.user_memory import UserMemory
from inspire_flow_backend.data.models.user_profile import UserProfile
from inspire_flow_backend.main import create_app
from inspire_flow_backend.schemas.memories import MemoryCategory
from inspire_flow_backend.schemas.projects import ProjectDraft
from inspire_flow_backend.services.agent.memory_extraction import (
    AcceptedMemoryCandidate,
    MemoryExtractionResult,
)
from inspire_flow_backend.services.agent.runtime import AgentRuntime
from inspire_flow_backend.services.injective import (
    ChainBroadcast,
    ChainBroadcastError,
    ChainConfirmation,
)

TEST_CONTEXT_KEY = "79zUG7lNhJ1eTm2N-oWpgStPtMzGxJTgQ3wp8bVh3Y0="


class FakeInjectiveProvider:
    network = "testnet"
    chain_id = "injective-888"

    def __init__(self) -> None:
        self.fail_next = False
        self.memos: list[str] = []
        self.confirmations: dict[str, ChainConfirmation] = {}
        self._counter = 0

    def broadcast(self, memo: str) -> ChainBroadcast:
        if self.fail_next:
            self.fail_next = False
            raise ChainBroadcastError("fake broadcast failure", retryable=True)
        self._counter += 1
        transaction_hash = f"0x{self._counter:064x}"
        self.memos.append(memo)
        return ChainBroadcast(
            network=self.network,
            chain_id=self.chain_id,
            transaction_hash=transaction_hash,
            explorer_url=(f"https://testnet.blockscout.injective.network/tx/{transaction_hash}"),
        )

    def get_transaction_status(self, transaction_hash: str) -> ChainConfirmation:
        return self.confirmations.get(transaction_hash, "confirmed")


class FakeApiConversationAgent:
    def __init__(self) -> None:
        self.fail_next = False
        self.histories: dict[UUID, list[dict[str, object]]] = {}
        self.model_inputs: dict[UUID, list[dict[str, object]]] = {}

    async def run(
        self,
        input,
        *,
        session,
        run_config,
        max_turns=None,
        context=None,
    ):
        del input, max_turns, context
        if self.fail_next:
            self.fail_next = False
            raise ModelBehaviorError("fake API model failure")
        history = await session.get_items()
        conversation_id = UUID(session.session_id)
        self.histories[conversation_id] = history
        if run_config.call_model_input_filter is not None:
            filtered = await run_config.call_model_input_filter(
                CallModelData(
                    model_data=ModelInputData(
                        input=history,
                        instructions="test",
                    ),
                    agent=Agent(name="FakeApiAgent", instructions="test"),
                    context=None,
                )
            )
            self.model_inputs[conversation_id] = filtered.input

        user_messages = [
            item.get("content")
            for item in history
            if item.get("role") == "user" and isinstance(item.get("content"), str)
        ]
        await session.add_items(
            [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": f"已接续 {len(user_messages)} 条用户消息",
                        }
                    ],
                }
            ]
        )
        return object()

    async def aclose(self) -> None:
        return None

    def run_streamed(
        self,
        input,
        *,
        session,
        run_config,
        max_turns=None,
        context=None,
    ):
        del input, max_turns, context
        agent = self

        class Result:
            async def stream_events(self):
                if agent.fail_next:
                    agent.fail_next = False
                    raise ModelBehaviorError("fake API streaming failure")
                history = await session.get_items()
                conversation_id = UUID(session.session_id)
                agent.histories[conversation_id] = history
                if run_config.call_model_input_filter is not None:
                    filtered = await run_config.call_model_input_filter(
                        CallModelData(
                            model_data=ModelInputData(
                                input=history,
                                instructions="test",
                            ),
                            agent=Agent(
                                name="FakeApiAgent",
                                instructions="test",
                            ),
                            context=None,
                        )
                    )
                    agent.model_inputs[conversation_id] = filtered.input
                yield SimpleNamespace(
                    type="raw_response_event",
                    data=SimpleNamespace(
                        type="response.output_text.delta",
                        delta="已接续 ",
                    ),
                )
                yield SimpleNamespace(
                    type="raw_response_event",
                    data=SimpleNamespace(
                        type="response.output_text.delta",
                        delta="流式回复",
                    ),
                )
                await session.add_items(
                    [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "已接续 流式回复",
                                }
                            ],
                        }
                    ]
                )

        return Result()


class FakeApiCompactor:
    async def compact(self, value) -> str:
        del value
        return "测试摘要"


class FakeApiMemoryExtractor:
    async def extract(self, user_message: str) -> MemoryExtractionResult:
        evidence = "我主要做科技视频"
        if evidence not in user_message:
            return MemoryExtractionResult(status="completed", candidates=())
        return MemoryExtractionResult(
            status="completed",
            candidates=(
                AcceptedMemoryCandidate(
                    category=MemoryCategory.creative_focus,
                    content="用户主要制作科技视频",
                    evidence=evidence,
                    is_sensitive=False,
                    origin="automatic",
                ),
            ),
        )


class FakeApiProjectDraftGenerator:
    def __init__(self) -> None:
        self.fail_next = False
        self.descriptions: list[str] = []

    async def generate(self, description: str) -> ProjectDraft:
        self.descriptions.append(description)
        if self.fail_next:
            self.fail_next = False
            raise ModelBehaviorError("fake project draft failure")
        return ProjectDraft(
            title="本地语音识别实测",
            type="科技数码",
            audience="希望保护隐私的创作者",
            summary="对比本地部署的速度和效果",
            icon_url=None,
        )


@pytest.fixture
def context_cipher(tmp_path: Path) -> ContextCipher:
    return ContextCipher.from_settings(
        Settings(
            _env_file=None,
            context_encryption_key=TEST_CONTEXT_KEY,
            context_encryption_key_file=tmp_path / "unused-context.key",
        )
    )


@pytest.fixture
def fake_agent_runtime() -> AgentRuntime:
    return AgentRuntime(
        conversation_agent=FakeApiConversationAgent(),
        compactor=FakeApiCompactor(),
        memory_extractor=FakeApiMemoryExtractor(),
        project_draft_generator=FakeApiProjectDraftGenerator(),
    )


@pytest.fixture
def db_session_factory(
    tmp_path: Path,
) -> Generator[sessionmaker[Session]]:
    register_models()
    database_path = tmp_path / "api.db"
    test_engine = create_database_engine(f"sqlite:///{database_path}")
    assert {
        AgentConversation.__tablename__,
        AgentMessage.__tablename__,
        AuthSession.__tablename__,
        Inspiration.__tablename__,
        Project.__tablename__,
        TranscriptionJob.__tablename__,
        User.__tablename__,
        UserMemory.__tablename__,
        UserProfile.__tablename__,
        "inspiration_projects",
    } <= set(Base.metadata.tables)
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture
def fake_injective_provider() -> FakeInjectiveProvider:
    return FakeInjectiveProvider()


@pytest.fixture
def client(
    db_session_factory: sessionmaker[Session],
    context_cipher: ContextCipher,
    fake_agent_runtime: AgentRuntime,
    fake_injective_provider: FakeInjectiveProvider,
) -> Generator[TestClient]:
    application = create_app()

    def override_db_session() -> Generator[Session]:
        with db_session_factory() as db:
            yield db

    async def override_agent_runtime() -> AgentRuntime:
        return fake_agent_runtime

    application.dependency_overrides[get_db_session] = override_db_session
    application.dependency_overrides[get_context_cipher] = lambda: context_cipher
    application.dependency_overrides[get_agent_runtime] = override_agent_runtime
    application.dependency_overrides[get_injective_provider] = lambda: fake_injective_provider
    application.dependency_overrides[get_agent_stream_runtime_factory] = lambda: (
        lambda: fake_agent_runtime
    )
    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()
