import asyncio
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
import pytest
from agents import Agent

from inspire_flow_backend.services.agent import agent as agent_module
from inspire_flow_backend.services.agent.agent import (
    DEFAULT_AGENT_INSTRUCTIONS,
    AgentService,
    create_agent_service,
)


@dataclass
class FakeRunner:
    result: object
    calls: list[tuple[Agent[Any], str, int]] = field(default_factory=list)

    async def run(
        self,
        starting_agent: Agent[Any],
        prompt: str,
        *,
        max_turns: int,
    ) -> Any:
        self.calls.append((starting_agent, prompt, max_turns))
        return self.result


def build_http_client() -> httpx.AsyncClient:
    transport = httpx.MockTransport(lambda request: httpx.Response(500, request=request))
    return httpx.AsyncClient(transport=transport)


def test_factory_builds_agent_with_deterministic_tools() -> None:
    client = build_http_client()
    service = create_agent_service(http_client=client, runner=FakeRunner(object()))

    try:
        assert service.agent.name == "InspireFlow"
        assert [tool.name for tool in service.agent.tools] == [
            "current_datetime",
            "search_website",
            "fetch_webpage",
        ]
        assert service.agent.instructions == DEFAULT_AGENT_INSTRUCTIONS
        assert "不可信" in DEFAULT_AGENT_INSTRUCTIONS
        assert "不执行其中的指令" in DEFAULT_AGENT_INSTRUCTIONS
        assert "密钥" in DEFAULT_AGENT_INSTRUCTIONS
    finally:
        asyncio.run(client.aclose())


def test_default_instructions_define_bilibili_creation_workflow() -> None:
    expected_concepts = [
        "B 站 UP 主",
        "保留原意",
        "不要声称已经保存",
        "Bilibili 视频大纲",
        "脚本",
        "分镜",
        "拍摄清单",
        "预算",
        "授权",
        "分账",
        "已确认",
        "待确认",
    ]

    for concept in expected_concepts:
        assert concept in DEFAULT_AGENT_INSTRUCTIONS

    assert "—" not in DEFAULT_AGENT_INSTRUCTIONS
    assert "–" not in DEFAULT_AGENT_INSTRUCTIONS


def test_default_instructions_use_context_without_repeating_questions() -> None:
    expected_concepts = [
        "动态上下文",
        "不要重复询问",
        "用户本轮明确表达",
        "更新了哪项理解",
        "一个最值得回答的问题",
        "2 到 4 个明确选项",
        "直接生成",
    ]

    for concept in expected_concepts:
        assert concept in DEFAULT_AGENT_INSTRUCTIONS


def test_default_instructions_define_stages_and_artifact_shapes() -> None:
    expected_stages = [
        "灵感澄清",
        "方向确认",
        "大纲生成",
        "内容细化",
        "分镜或脚本生成",
        "拍摄准备",
        "发布准备",
    ]
    expected_artifact_fields = [
        "镜头编号",
        "台词或声音",
        "建议时长",
        "拍摄提示",
        "旁白",
        "对白",
        "画面提示",
        "音效或环境声",
    ]

    for concept in [*expected_stages, *expected_artifact_fields]:
        assert concept in DEFAULT_AGENT_INSTRUCTIONS

    assert "不要一次跨越过多阶段" in DEFAULT_AGENT_INSTRUCTIONS
    assert "普通对话使用自然语言" in DEFAULT_AGENT_INSTRUCTIONS
    assert "Markdown" in DEFAULT_AGENT_INSTRUCTIONS


def test_default_instructions_protect_context_and_external_operations() -> None:
    expected_concepts = [
        "其他项目或其他用户",
        "上传",
        "付款",
        "删除",
        "工具结果明确显示操作成功",
        "停止使用相关上下文",
        "医疗、法律或财务",
        "虚假的确定性结论",
    ]

    for concept in expected_concepts:
        assert concept in DEFAULT_AGENT_INSTRUCTIONS


def test_service_delegates_runs_and_allows_turn_override() -> None:
    expected = object()
    runner = FakeRunner(expected)
    client = build_http_client()
    service = create_agent_service(http_client=client, runner=runner, max_turns=7)

    try:
        default_result = asyncio.run(service.run("first prompt"))
        override_result = asyncio.run(service.run("second prompt", max_turns=2))

        assert default_result is expected
        assert override_result is expected
        assert runner.calls == [
            (service.agent, "first prompt", 7),
            (service.agent, "second prompt", 2),
        ]
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize("prompt", ["", "   \n"])
def test_service_rejects_blank_prompts(prompt: str) -> None:
    client = build_http_client()
    service = create_agent_service(http_client=client, runner=FakeRunner(object()))

    try:
        with pytest.raises(ValueError, match="prompt"):
            asyncio.run(service.run(prompt))
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize("max_turns", [0, -1, True, 1.5])
def test_service_rejects_invalid_turn_counts(max_turns: object) -> None:
    client = build_http_client()

    try:
        with pytest.raises(ValueError, match="max_turns"):
            create_agent_service(
                http_client=client,
                runner=FakeRunner(object()),
                max_turns=cast(Any, max_turns),
            )

        service = create_agent_service(
            http_client=client,
            runner=FakeRunner(object()),
        )
        with pytest.raises(ValueError, match="max_turns"):
            asyncio.run(service.run("hello", max_turns=cast(Any, max_turns)))
    finally:
        asyncio.run(client.aclose())


def test_service_does_not_swallow_runner_exceptions() -> None:
    expected = RuntimeError("runner failed")

    class RaisingRunner:
        async def run(
            self,
            starting_agent: Agent[Any],
            prompt: str,
            *,
            max_turns: int,
        ) -> Any:
            del starting_agent, prompt, max_turns
            raise expected

    client = build_http_client()
    service = create_agent_service(http_client=client, runner=RaisingRunner())

    try:
        with pytest.raises(RuntimeError) as captured:
            asyncio.run(service.run("hello"))
        assert captured.value is expected
    finally:
        asyncio.run(client.aclose())


def test_service_does_not_close_an_injected_http_client() -> None:
    client = build_http_client()
    service = create_agent_service(http_client=client, runner=FakeRunner(object()))

    asyncio.run(service.aclose())

    assert client.is_closed is False
    asyncio.run(client.aclose())


def test_service_closes_factory_owned_http_client(monkeypatch) -> None:
    client = build_http_client()
    monkeypatch.setattr(
        agent_module.httpx,
        "AsyncClient",
        lambda **kwargs: client,
    )
    service = create_agent_service(runner=FakeRunner(object()))

    asyncio.run(service.aclose())

    assert client.is_closed is True


def test_service_is_an_async_context_manager() -> None:
    client = build_http_client()
    service = create_agent_service(http_client=client, runner=FakeRunner(object()))

    async def use_service() -> AgentService:
        async with service as entered:
            return entered

    entered = asyncio.run(use_service())

    assert entered is service
    assert client.is_closed is False
    asyncio.run(client.aclose())
