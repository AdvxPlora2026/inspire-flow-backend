from dataclasses import dataclass, field
from typing import Protocol

from agents import (
    Agent,
    Model,
    RunConfig,
    RunResult,
    RunResultStreaming,
    Session,
    TResponseInputItem,
)
from openai import AsyncOpenAI

from inspire_flow_backend.core.config import (
    ModelSettings,
    get_model_settings,
)
from inspire_flow_backend.core.errors import AgentUnavailableError
from inspire_flow_backend.services.agent.agent import (
    AgentService,
    OpenAIAgentRunner,
    create_agent_service,
)
from inspire_flow_backend.services.agent.compaction import (
    ContextCompactor,
    ModelContextCompactor,
)
from inspire_flow_backend.services.agent.contracts import AgentRunContext, TextGenerator
from inspire_flow_backend.services.agent.memory_extraction import (
    MemoryExtractor,
    ModelMemoryExtractor,
)
from inspire_flow_backend.services.agent.project_drafting import (
    ModelProjectDraftGenerator,
    ProjectDraftGenerator,
)


class ConversationAgent(Protocol):
    async def run(
        self,
        input: str | list[TResponseInputItem],
        *,
        max_turns: int | None = None,
        session: Session | None = None,
        run_config: RunConfig | None = None,
        context: AgentRunContext | None = None,
    ) -> object: ...

    def run_streamed(
        self,
        input: str | list[TResponseInputItem],
        *,
        max_turns: int | None = None,
        session: Session | None = None,
        run_config: RunConfig | None = None,
        context: AgentRunContext | None = None,
    ) -> RunResultStreaming: ...

    async def aclose(self) -> None: ...


class AgentTextGenerator(TextGenerator):
    def __init__(
        self,
        *,
        name: str,
        instructions: str,
        model: Model,
        max_turns: int = 3,
    ) -> None:
        self._agent = Agent(
            name=name,
            instructions=instructions,
            model=model,
            tools=[],
        )
        self._runner = OpenAIAgentRunner()
        self._max_turns = max_turns

    async def generate(self, prompt: str) -> str:
        result: RunResult = await self._runner.run(
            self._agent,
            prompt,
            max_turns=self._max_turns,
        )
        output = result.final_output
        if not isinstance(output, str):
            raise ValueError("Agent text generator returned a non-text output")
        return output


def _normalize_openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    chat_completions_suffix = "/chat/completions"
    if normalized.endswith(chat_completions_suffix):
        return normalized[: -len(chat_completions_suffix)]
    return normalized


@dataclass
class AgentRuntime:
    conversation_agent: ConversationAgent
    compactor: ContextCompactor
    memory_extractor: MemoryExtractor
    project_draft_generator: ProjectDraftGenerator
    _model_client: AsyncOpenAI | None = field(default=None, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.conversation_agent.aclose()
        finally:
            if self._model_client is not None:
                await self._model_client.close()


def create_agent_runtime(
    settings: ModelSettings | None = None,
) -> AgentRuntime:
    from agents import OpenAIChatCompletionsModel

    configured = settings or get_model_settings()
    if (
        configured.api_key is None
        or configured.name is None
        or not configured.name.strip()
        or configured.base_url is None
    ):
        raise AgentUnavailableError

    client = AsyncOpenAI(
        api_key=configured.api_key.get_secret_value(),
        base_url=_normalize_openai_base_url(str(configured.base_url)),
    )
    model = OpenAIChatCompletionsModel(
        model=configured.name,
        openai_client=client,
    )
    conversation_agent: AgentService = create_agent_service(model=model)
    compaction_generator = AgentTextGenerator(
        name="InspireFlowContextCompactor",
        instructions=("你只负责把创作对话压缩为忠实、简洁的中文摘要，不添加新事实。"),
        model=model,
    )
    extraction_generator = AgentTextGenerator(
        name="InspireFlowMemoryExtractor",
        instructions=("你只从用户明确表达中提取长期记忆候选，并严格输出要求的 JSON。"),
        model=model,
    )
    return AgentRuntime(
        conversation_agent=conversation_agent,
        compactor=ModelContextCompactor(compaction_generator),
        memory_extractor=ModelMemoryExtractor(extraction_generator),
        project_draft_generator=ModelProjectDraftGenerator(model=model),
        _model_client=client,
    )
