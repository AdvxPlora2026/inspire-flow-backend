import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
from agents import Agent, ModelBehaviorError

from inspire_flow_backend.core.errors import AgentRunFailedError
from inspire_flow_backend.schemas.projects import ProjectDraft
from inspire_flow_backend.services.agent.project_drafting import (
    ModelProjectDraftGenerator,
)
from inspire_flow_backend.services.projects import draft_project


@dataclass
class FakeRunResult:
    final_output: object


class FakeRunner:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls: list[tuple[Agent[Any], str, int]] = []

    async def run(
        self,
        starting_agent: Agent[Any],
        input: str,
        *,
        max_turns: int,
        **kwargs: object,
    ) -> FakeRunResult:
        del kwargs
        self.calls.append((starting_agent, input, max_turns))
        return FakeRunResult(final_output=self.output)


class FakeDraftGenerator:
    async def generate(self, description: str) -> ProjectDraft:
        assert description == "做一期本地语音识别视频"
        return ProjectDraft(
            title=" 本地语音识别实测 ",
            type=" 科技数码 ",
            audience=" 希望保护隐私的创作者 ",
            summary=" 对比本地部署的速度和效果 ",
        )


class FailingDraftGenerator:
    async def generate(self, description: str) -> ProjectDraft:
        del description
        raise ModelBehaviorError("invalid structured output")


class UnexpectedFailingDraftGenerator:
    async def generate(self, description: str) -> ProjectDraft:
        del description
        raise RuntimeError("programming defect")


def test_model_project_drafter_uses_typed_output_without_tools() -> None:
    expected = ProjectDraft(
        title="本地语音识别实测",
        type="科技数码",
        audience="希望保护隐私的创作者",
        summary="对比本地部署的速度和效果",
    )
    runner = FakeRunner(expected)
    generator = ModelProjectDraftGenerator(model="test-model", runner=runner)

    result = asyncio.run(generator.generate("做一期本地语音识别视频"))

    assert result == expected
    agent, prompt, max_turns = runner.calls[0]
    assert prompt == "做一期本地语音识别视频"
    assert max_turns == 2
    assert agent.name == "InspireFlowProjectDrafter"
    assert agent.tools == []
    assert agent.output_type is not None


def test_draft_project_returns_normalized_typed_draft() -> None:
    result = asyncio.run(
        draft_project(
            "做一期本地语音识别视频",
            FakeDraftGenerator(),
        )
    )

    assert result.model_dump() == {
        "title": "本地语音识别实测",
        "type": "科技数码",
        "audience": "希望保护隐私的创作者",
        "summary": "对比本地部署的速度和效果",
    }


def test_draft_project_maps_expected_agent_failure() -> None:
    with pytest.raises(AgentRunFailedError):
        asyncio.run(draft_project("描述", FailingDraftGenerator()))


def test_draft_project_does_not_hide_unexpected_defects() -> None:
    with pytest.raises(RuntimeError, match="programming defect"):
        asyncio.run(draft_project("描述", UnexpectedFailingDraftGenerator()))
