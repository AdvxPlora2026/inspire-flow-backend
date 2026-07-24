import asyncio
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from agents import Agent, RunConfig, Session, TResponseInputItem
from sqlalchemy.orm import Session as DatabaseSession

from inspire_flow_backend.services.agent import agent as agent_module
from inspire_flow_backend.services.agent.agent import (
    DEFAULT_AGENT_INSTRUCTIONS,
    AgentService,
    create_agent_service,
)
from inspire_flow_backend.services.agent.contracts import AgentRunContext


@dataclass
class RunnerCall:
    starting_agent: Agent[Any]
    input: str | list[TResponseInputItem]
    max_turns: int
    session: Session | None
    run_config: RunConfig | None
    context: AgentRunContext | None


@dataclass
class FakeRunner:
    result: object
    calls: list[RunnerCall] = field(default_factory=list)
    stream_calls: list[RunnerCall] = field(default_factory=list)

    async def run(
        self,
        starting_agent: Agent[Any],
        input: str | list[TResponseInputItem],
        *,
        max_turns: int,
        session: Session | None = None,
        run_config: RunConfig | None = None,
        context: AgentRunContext | None = None,
    ) -> Any:
        self.calls.append(
            RunnerCall(
                starting_agent=starting_agent,
                input=input,
                max_turns=max_turns,
                session=session,
                run_config=run_config,
                context=context,
            )
        )
        return self.result

    def run_streamed(
        self,
        starting_agent: Agent[Any],
        input: str | list[TResponseInputItem],
        *,
        max_turns: int,
        session: Session | None = None,
        run_config: RunConfig | None = None,
        context: AgentRunContext | None = None,
    ) -> Any:
        self.stream_calls.append(
            RunnerCall(
                starting_agent=starting_agent,
                input=input,
                max_turns=max_turns,
                session=session,
                run_config=run_config,
                context=context,
            )
        )
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
            "create_project",
            "list_projects",
            "get_project",
            "update_project",
            "delete_project",
            "create_inspiration",
            "list_inspirations",
            "get_inspiration",
            "update_inspiration",
            "delete_inspiration",
            "add_inspiration_project",
            "remove_inspiration_project",
            "update_current_user",
            "update_user_profile_text",
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


def test_default_instructions_define_user_profile_mutation_boundaries() -> None:
    expected_concepts = [
        "用户明确提出",
        "昵称",
        "头像",
        "用户画像",
        "主动归纳",
        "跨会话",
        "敏感信息",
        "不得把推测写成事实",
    ]

    for concept in expected_concepts:
        assert concept in DEFAULT_AGENT_INSTRUCTIONS


def test_default_instructions_require_project_mutation_confirmation() -> None:
    expected_concepts = [
        "项目草稿",
        "明确确认保存",
        "单独一轮",
        "确认删除",
        "其他用户",
    ]

    for concept in expected_concepts:
        assert concept in DEFAULT_AGENT_INSTRUCTIONS


def test_default_instructions_define_inspiration_persistence_boundaries() -> None:
    expected_concepts = [
        "清晰、可识别的创作想法",
        "自动保存",
        "一般讨论",
        "先询问是否保存",
        "来源对话",
        "项目关联",
        "受影响灵感",
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
        assert [(call.input, call.max_turns) for call in runner.calls] == [
            ("first prompt", 7),
            ("second prompt", 2),
        ]
        assert all(call.starting_agent is service.agent for call in runner.calls)
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


def test_service_delegates_session_input_and_run_config() -> None:
    runner = FakeRunner(object())
    client = build_http_client()
    service = create_agent_service(http_client=client, runner=runner)
    expected_session = cast(Session, object())
    expected_config = RunConfig(trace_include_sensitive_data=False)

    try:
        asyncio.run(
            service.run(
                [],
                session=expected_session,
                run_config=expected_config,
            )
        )

        call = runner.calls[-1]
        assert call.input == []
        assert call.session is expected_session
        assert call.run_config is expected_config
    finally:
        asyncio.run(client.aclose())


def test_service_delegates_streamed_session_input_and_run_config() -> None:
    expected_result = object()
    runner = FakeRunner(expected_result)
    client = build_http_client()
    service = create_agent_service(http_client=client, runner=runner)
    expected_session = cast(Session, object())
    expected_config = RunConfig(trace_include_sensitive_data=False)

    try:
        result = service.run_streamed(
            [],
            session=expected_session,
            run_config=expected_config,
        )

        assert result is expected_result
        call = runner.stream_calls[-1]
        assert call.input == []
        assert call.session is expected_session
        assert call.run_config is expected_config
    finally:
        asyncio.run(client.aclose())


def test_service_forwards_trusted_project_context() -> None:
    runner = FakeRunner(object())
    client = build_http_client()
    service = create_agent_service(http_client=client, runner=runner)
    context = AgentRunContext(db=cast(DatabaseSession, object()), user_id=uuid4())

    try:
        asyncio.run(service.run("继续项目", context=context))

        assert runner.calls[-1].context is context
    finally:
        asyncio.run(client.aclose())


def test_service_rejects_empty_input_without_session() -> None:
    client = build_http_client()
    service = create_agent_service(http_client=client, runner=FakeRunner(object()))

    try:
        with pytest.raises(ValueError, match="session"):
            asyncio.run(service.run([]))
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
            input: str | list[TResponseInputItem],
            *,
            max_turns: int,
            session: Session | None = None,
            run_config: RunConfig | None = None,
            context: AgentRunContext | None = None,
        ) -> Any:
            del starting_agent, input, max_turns, session, run_config, context
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
