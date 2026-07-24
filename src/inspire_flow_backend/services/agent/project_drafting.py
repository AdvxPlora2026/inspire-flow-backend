from typing import Any, Protocol

from agents import Agent, Model, ModelBehaviorError

from inspire_flow_backend.schemas.projects import ProjectDraft
from inspire_flow_backend.services.agent.agent import (
    AgentRunner,
    OpenAIAgentRunner,
)

PROJECT_DRAFT_INSTRUCTIONS = """根据用户对创作想法的描述，生成一个待确认的项目草稿。
只输出标题、类型、受众和简介，不声称已经保存项目。
标题应简洁具体；类型使用常见的 Bilibili 视频分区或用户描述中的自定义类型；
受众说明最适合观看这项内容的人群；简介忠实概括作品方向，不编造事实。
信息不足时可以给出保守、可编辑的草案，不添加用户未提供的经历、数据或合作关系。"""


class ProjectDraftGenerator(Protocol):
    async def generate(self, description: str) -> ProjectDraft: ...


class ModelProjectDraftGenerator:
    def __init__(
        self,
        *,
        model: str | Model,
        runner: AgentRunner | None = None,
    ) -> None:
        self._agent: Agent[Any] = Agent(
            name="InspireFlowProjectDrafter",
            instructions=PROJECT_DRAFT_INSTRUCTIONS,
            model=model,
            tools=[],
            output_type=ProjectDraft,
        )
        self._runner = runner or OpenAIAgentRunner()

    async def generate(self, description: str) -> ProjectDraft:
        result = await self._runner.run(
            self._agent,
            description,
            max_turns=2,
        )
        output = result.final_output
        if not isinstance(output, ProjectDraft):
            raise ModelBehaviorError("Project drafter returned an invalid output")
        return output
