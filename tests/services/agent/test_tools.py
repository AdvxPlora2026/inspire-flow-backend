import asyncio
import importlib
import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from agents.tool_context import ToolContext
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.database import create_database_engine
from inspire_flow_backend.data.model_registry import register_models
from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.data.models.inspiration import Inspiration
from inspire_flow_backend.data.models.project import Project
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.services.agent.contracts import (
    AgentRunContext,
    AgentToolError,
    AgentToolSettings,
)
from inspire_flow_backend.services.agent.func import (
    build_agent_tools,
    get_current_datetime,
)

FIXED_NOW = datetime(2026, 7, 23, 10, 30, tzinfo=UTC)


def fixed_clock() -> datetime:
    return FIXED_NOW


def build_tools():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500, request=request),
        )
    )
    tools = build_agent_tools(
        http_client=client,
        settings=AgentToolSettings(),
        clock=fixed_clock,
        resolver=None,
    )
    return client, tools


def invoke_tool(tool, arguments: dict[str, object]) -> str:
    return asyncio.run(invoke_tool_async(tool, arguments))


def test_agent_functions_are_defined_under_func_package() -> None:
    expected_definitions = {
        "inspire_flow_backend.services.agent.func.current_datetime": [
            "build_current_datetime_tool",
            "get_current_datetime",
        ],
        "inspire_flow_backend.services.agent.func.search_website": [
            "build_search_website_tool",
        ],
        "inspire_flow_backend.services.agent.func.fetch_webpage": [
            "build_fetch_webpage_tool",
        ],
        "inspire_flow_backend.services.agent.func.create_project": [
            "build_create_project_tool",
        ],
        "inspire_flow_backend.services.agent.func.list_projects": [
            "build_list_projects_tool",
        ],
        "inspire_flow_backend.services.agent.func.get_project": [
            "build_get_project_tool",
        ],
        "inspire_flow_backend.services.agent.func.update_project": [
            "build_update_project_tool",
        ],
        "inspire_flow_backend.services.agent.func.delete_project": [
            "build_delete_project_tool",
        ],
        "inspire_flow_backend.services.agent.func.create_inspiration": [
            "build_create_inspiration_tool",
        ],
        "inspire_flow_backend.services.agent.func.list_inspirations": [
            "build_list_inspirations_tool",
        ],
        "inspire_flow_backend.services.agent.func.get_inspiration": [
            "build_get_inspiration_tool",
        ],
        "inspire_flow_backend.services.agent.func.update_inspiration": [
            "build_update_inspiration_tool",
        ],
        "inspire_flow_backend.services.agent.func.delete_inspiration": [
            "build_delete_inspiration_tool",
        ],
        "inspire_flow_backend.services.agent.func.add_inspiration_project": [
            "build_add_inspiration_project_tool",
        ],
        "inspire_flow_backend.services.agent.func.remove_inspiration_project": [
            "build_remove_inspiration_project_tool",
        ],
        "inspire_flow_backend.services.agent.func.update_current_user": [
            "build_update_current_user_tool",
        ],
        "inspire_flow_backend.services.agent.func.update_user_profile_text": [
            "build_update_user_profile_text_tool",
        ],
        "inspire_flow_backend.services.agent.func.registry": [
            "build_agent_tools",
        ],
    }

    for module_name, definitions in expected_definitions.items():
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            pytest.fail(f"Agent function module is missing: {module_name}")

        for definition in definitions:
            value = getattr(module, definition)
            assert value.__module__ == module_name


async def invoke_tool_async(
    tool,
    arguments: dict[str, object],
    context: AgentRunContext | None = None,
) -> str:
    arguments_json = json.dumps(arguments)
    context = ToolContext(
        context=context,
        tool_name=tool.name,
        tool_call_id="test-call",
        tool_arguments=arguments_json,
    )
    return await tool.on_invoke_tool(context, arguments_json)


def invoke_project_tool(
    tool,
    arguments: dict[str, object],
    context: AgentRunContext | None,
) -> dict[str, object]:
    return json.loads(asyncio.run(invoke_tool_async(tool, arguments, context)))


def add_user(db: Session, nickname: str) -> User:
    now = utc_now()
    user = User(
        id=uuid4(),
        nickname=nickname,
        nickname_key=nickname.casefold(),
        password_hash="test-only-hash",
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    db.commit()
    return user


def test_current_datetime_defaults_to_utc() -> None:
    result = get_current_datetime("UTC", fixed_clock)

    assert result.model_dump() == {
        "ok": True,
        "timezone": "UTC",
        "iso_datetime": "2026-07-23T10:30:00+00:00",
        "unix_timestamp": int(FIXED_NOW.timestamp()),
    }


def test_current_datetime_converts_to_iana_timezone() -> None:
    result = get_current_datetime("Asia/Shanghai", fixed_clock)

    assert result.timezone == "Asia/Shanghai"
    assert result.iso_datetime == "2026-07-23T18:30:00+08:00"
    assert result.unix_timestamp == int(FIXED_NOW.timestamp())


def test_current_datetime_rejects_unknown_timezone() -> None:
    with pytest.raises(AgentToolError) as captured:
        get_current_datetime("Mars/Olympus_Mons", fixed_clock)

    assert captured.value.code == "invalid_timezone"
    assert captured.value.message == "Unknown IANA timezone"


def test_current_datetime_function_tool_has_stable_schema_and_output() -> None:
    client, tools = build_tools()
    tool = tools[0]

    try:
        assert tool.name == "current_datetime"
        assert tool.params_json_schema["properties"]["timezone_name"] == {
            "default": "UTC",
            "description": "IANA timezone such as UTC or Asia/Shanghai.",
            "title": "Timezone Name",
            "type": "string",
        }
        output = json.loads(invoke_tool(tool, {"timezone_name": "Asia/Shanghai"}))
        assert output == {
            "ok": True,
            "timezone": "Asia/Shanghai",
            "iso_datetime": "2026-07-23T18:30:00+08:00",
            "unix_timestamp": int(FIXED_NOW.timestamp()),
        }
    finally:
        asyncio.run(client.aclose())


def test_current_datetime_function_tool_returns_safe_error() -> None:
    client, tools = build_tools()

    try:
        output = json.loads(
            invoke_tool(
                tools[0],
                {"timezone_name": "Mars/Olympus_Mons"},
            )
        )
        assert output == {
            "ok": False,
            "error": {
                "code": "invalid_timezone",
                "message": "Unknown IANA timezone",
            },
        }
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize(
    "overrides",
    [
        {"request_timeout_seconds": 0},
        {"tool_timeout_seconds": 0},
        {"default_search_results": 0},
        {"default_search_results": 6, "max_search_results": 5},
        {"max_search_results": 0},
        {"max_query_characters": 0},
        {"max_search_response_bytes": 0},
        {"max_fetch_response_bytes": 0},
        {"max_fetch_output_characters": 0},
        {"max_redirects": -1},
        {"max_search_results": 1.5},
        {"request_timeout_seconds": float("inf")},
        {"tool_timeout_seconds": float("nan")},
        {"user_agent": "  "},
        {"user_agent": 123},
    ],
)
def test_tool_settings_reject_invalid_limits(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        AgentToolSettings(**cast(Any, overrides))


def test_tool_settings_allow_zero_redirects() -> None:
    assert AgentToolSettings(max_redirects=0).max_redirects == 0


def test_network_tool_schemas_are_stable_and_use_injected_default() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500, request=request),
        )
    )
    tools = build_agent_tools(
        http_client=client,
        settings=AgentToolSettings(default_search_results=2),
        clock=fixed_clock,
        resolver=None,
    )

    try:
        assert tools[1].name == "search_website"
        assert tools[1].params_json_schema["properties"] == {
            "query": {
                "description": "Search terms.",
                "title": "Query",
                "type": "string",
            },
            "max_results": {
                "default": 2,
                "description": "Maximum number of results to return.",
                "title": "Max Results",
                "type": "integer",
            },
        }
        assert tools[2].name == "fetch_webpage"
        assert tools[2].params_json_schema["properties"] == {
            "url": {
                "description": "Public webpage URL.",
                "title": "Url",
                "type": "string",
            }
        }
    finally:
        asyncio.run(client.aclose())


def test_search_website_tool_returns_duckduckgo_results() -> None:
    html = """
    <a class="result__a"
       href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F">
      Example
    </a>
    <div class="result__snippet">An example result.</div>
    """
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=html, request=request),
        )
    )
    tools = build_agent_tools(
        http_client=client,
        settings=AgentToolSettings(),
        clock=fixed_clock,
        resolver=None,
    )

    try:
        output = json.loads(
            invoke_tool(
                tools[1],
                {"query": "example", "max_results": 1},
            )
        )
        assert output == {
            "ok": True,
            "query": "example",
            "provider": "duckduckgo",
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.com/",
                    "snippet": "An example result.",
                }
            ],
        }
    finally:
        asyncio.run(client.aclose())


def test_search_website_tool_returns_safe_validation_error() -> None:
    client, tools = build_tools()

    try:
        output = json.loads(invoke_tool(tools[1], {"query": "", "max_results": 5}))
        assert output == {
            "ok": False,
            "error": {
                "code": "invalid_query",
                "message": "Search query is empty or too long",
            },
        }
    finally:
        asyncio.run(client.aclose())


def test_fetch_webpage_tool_returns_readable_content() -> None:
    async def public_resolver(hostname: str) -> set[str]:
        assert hostname == "example.com"
        return {"93.184.216.34"}

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text="<title>Example</title><main>Hello world</main>",
                headers={"Content-Type": "text/html"},
                request=request,
            ),
        )
    )
    tools = build_agent_tools(
        http_client=client,
        settings=AgentToolSettings(),
        clock=fixed_clock,
        resolver=public_resolver,
    )

    try:
        output = json.loads(invoke_tool(tools[2], {"url": "https://example.com/"}))
        assert output == {
            "ok": True,
            "url": "https://example.com/",
            "content_type": "text/html",
            "title": "Example",
            "text": "Hello world",
            "truncated": False,
        }
    finally:
        asyncio.run(client.aclose())


def test_fetch_webpage_tool_returns_safe_url_error() -> None:
    client, tools = build_tools()

    try:
        output = json.loads(invoke_tool(tools[2], {"url": "http://127.0.0.1/"}))
        assert output["ok"] is False
        assert output["error"]["code"] == "unsafe_url"
    finally:
        asyncio.run(client.aclose())


def test_network_tool_does_not_hide_unexpected_errors() -> None:
    expected = RuntimeError("transport defect")

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise expected

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tools = build_agent_tools(
        http_client=client,
        settings=AgentToolSettings(),
        clock=fixed_clock,
        resolver=None,
    )

    try:
        with pytest.raises(RuntimeError) as captured:
            invoke_tool(tools[1], {"query": "python", "max_results": 5})
        assert captured.value is expected
    finally:
        asyncio.run(client.aclose())


def test_network_tool_timeout_is_configured_as_safe_json_result() -> None:
    client, tools = build_tools()
    search_tool = tools[1]
    fetch_tool = tools[2]
    timeout_formatter = search_tool.timeout_error_function
    context = ToolContext(
        context=None,
        tool_name=search_tool.name,
        tool_call_id="test-call",
        tool_arguments='{"query":"python","max_results":5}',
    )

    try:
        assert search_tool.timeout_seconds == 15.0
        assert search_tool.timeout_behavior == "error_as_result"
        assert timeout_formatter is not None
        output = json.loads(timeout_formatter(context, TimeoutError()))
        assert output == {
            "ok": False,
            "error": {
                "code": "search_unavailable",
                "message": "Search tool timed out",
            },
        }

        fetch_formatter = fetch_tool.timeout_error_function
        assert fetch_tool.timeout_seconds == 15.0
        assert fetch_formatter is not None
        fetch_output = json.loads(fetch_formatter(context, TimeoutError()))
        assert fetch_output["error"] == {
            "code": "fetch_unavailable",
            "message": "Webpage fetch tool timed out",
        }
    finally:
        asyncio.run(client.aclose())


def test_project_tool_schemas_hide_owner_context() -> None:
    client, tools = build_tools()

    try:
        project_tools = tools[3:8]
        assert [tool.name for tool in project_tools] == [
            "create_project",
            "list_projects",
            "get_project",
            "update_project",
            "delete_project",
        ]
        for tool in project_tools:
            properties = tool.params_json_schema.get("properties", {})
            assert "user_id" not in properties
            assert "ctx" not in properties
        for tool in tools[8:]:
            properties = tool.params_json_schema.get("properties", {})
            assert "user_id" not in properties
            assert "conversation_id" not in properties
            assert "source_message_id" not in properties
            assert "ctx" not in properties
    finally:
        asyncio.run(client.aclose())


def test_user_tools_update_only_the_context_user_and_return_safe_results() -> None:
    register_models()
    engine = create_database_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    client, tools = build_tools()
    try:
        tools_by_name = {tool.name: tool for tool in tools}
        assert {"update_current_user", "update_user_profile_text"} <= set(tools_by_name)
        with factory() as db:
            owner = add_user(db, "profile-tool-owner")
            other = add_user(db, "profile-tool-other")
            context = AgentRunContext(db=db, user_id=owner.id)

            updated = invoke_project_tool(
                tools_by_name["update_current_user"],
                {
                    "nickname": "Profile Tool Renamed",
                    "avatar_url": "https://cdn.example.com/profile.png",
                },
                context,
            )
            assert updated["ok"] is True
            assert updated["user"]["id"] == str(owner.id)
            assert updated["user"]["nickname"] == "Profile Tool Renamed"
            assert updated["user"]["avatar_url"] == "https://cdn.example.com/profile.png"
            assert "password_hash" not in json.dumps(updated)

            portrait = invoke_project_tool(
                tools_by_name["update_user_profile_text"],
                {"profile_text": "  偏好有数据支撑的科技视频  "},
                context,
            )
            assert portrait == {
                "ok": True,
                "profile_text": "偏好有数据支撑的科技视频",
            }
            db.refresh(owner)
            db.refresh(other)
            assert owner.profile_text == "偏好有数据支撑的科技视频"
            assert other.profile_text is None

            cleared_avatar = invoke_project_tool(
                tools_by_name["update_current_user"],
                {"clear_avatar": True},
                context,
            )
            assert cleared_avatar["user"]["avatar_url"] is None
            cleared_portrait = invoke_project_tool(
                tools_by_name["update_user_profile_text"],
                {"clear_profile_text": True},
                context,
            )
            assert cleared_portrait == {"ok": True, "profile_text": None}
    finally:
        asyncio.run(client.aclose())
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_user_tools_validate_conflicts_and_missing_context_safely() -> None:
    register_models()
    engine = create_database_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    client, tools = build_tools()
    try:
        tools_by_name = {tool.name: tool for tool in tools}
        assert {"update_current_user", "update_user_profile_text"} <= set(tools_by_name)
        with factory() as db:
            owner = add_user(db, "user-tool-owner")
            add_user(db, "user-tool-taken")
            context = AgentRunContext(db=db, user_id=owner.id)

            conflict = invoke_project_tool(
                tools_by_name["update_current_user"],
                {"nickname": "USER-TOOL-TAKEN"},
                context,
            )
            assert conflict["error"]["code"] == "nickname_conflict"

            invalid_user = invoke_project_tool(
                tools_by_name["update_current_user"],
                {
                    "avatar_url": "https://cdn.example.com/profile.png",
                    "clear_avatar": True,
                },
                context,
            )
            assert invalid_user["error"]["code"] == "invalid_user"

            invalid_portrait = invoke_project_tool(
                tools_by_name["update_user_profile_text"],
                {
                    "profile_text": "画像",
                    "clear_profile_text": True,
                },
                context,
            )
            assert invalid_portrait["error"]["code"] == "invalid_user_profile_text"

            too_long = invoke_project_tool(
                tools_by_name["update_user_profile_text"],
                {"profile_text": "x" * 8001},
                context,
            )
            assert too_long["error"]["code"] == "invalid_user_profile_text"

            credential = invoke_project_tool(
                tools_by_name["update_user_profile_text"],
                {"profile_text": "api_key=test-secret-placeholder"},
                context,
            )
            assert credential["error"]["code"] == "invalid_user_profile_text"
            db.refresh(owner)
            assert owner.profile_text is None

            for tool_name, arguments in [
                ("update_current_user", {"nickname": "New Name"}),
                ("update_user_profile_text", {"profile_text": "画像"}),
            ]:
                unavailable = invoke_project_tool(
                    tools_by_name[tool_name],
                    arguments,
                    None,
                )
                assert unavailable == {
                    "ok": False,
                    "error": {
                        "code": "user_context_unavailable",
                        "message": "Authenticated user context is unavailable",
                    },
                }
    finally:
        asyncio.run(client.aclose())
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_project_tools_enforce_confirmation_and_user_isolation() -> None:
    register_models()
    engine = create_database_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    client, tools = build_tools()
    try:
        with factory() as db:
            owner = add_user(db, "tool-owner")
            other = add_user(db, "tool-other")
            owner_context = AgentRunContext(db=db, user_id=owner.id)
            other_context = AgentRunContext(db=db, user_id=other.id)
            draft_arguments = {
                "title": "MPS 实测",
                "type": "科技数码",
                "audience": "Mac 用户",
                "summary": "本地部署语音识别",
                "icon_url": "https://cdn.example.com/project.png",
                "confirmed": False,
            }

            draft = invoke_project_tool(tools[3], draft_arguments, owner_context)
            assert draft["ok"] is True
            assert draft["status"] == "confirmation_required"
            assert draft["draft"]["title"] == "MPS 实测"
            assert draft["draft"]["icon_url"] == "https://cdn.example.com/project.png"
            assert db.scalar(select(func.count()).select_from(Project)) == 0

            created = invoke_project_tool(
                tools[3],
                {**draft_arguments, "confirmed": True},
                owner_context,
            )
            assert created["ok"] is True
            assert created["status"] == "created"
            project_id = created["project"]["id"]
            assert created["project"]["icon_url"] == "https://cdn.example.com/project.png"
            assert db.scalar(select(func.count()).select_from(Project)) == 1

            listed = invoke_project_tool(tools[4], {}, owner_context)
            assert listed["total"] == 1
            assert listed["projects"][0]["id"] == project_id
            assert invoke_project_tool(tools[4], {}, other_context)["total"] == 0

            fetched = invoke_project_tool(
                tools[5],
                {"project_id": project_id},
                owner_context,
            )
            assert fetched["project"]["title"] == "MPS 实测"
            hidden = invoke_project_tool(
                tools[5],
                {"project_id": project_id},
                other_context,
            )
            assert hidden == {
                "ok": False,
                "error": {
                    "code": "project_not_found",
                    "message": "Project not found",
                },
            }
            assert (
                invoke_project_tool(
                    tools[6],
                    {"project_id": project_id, "summary": "越权修改"},
                    other_context,
                )
                == hidden
            )
            assert (
                invoke_project_tool(
                    tools[7],
                    {"project_id": project_id, "confirmed": True},
                    other_context,
                )
                == hidden
            )

            updated = invoke_project_tool(
                tools[6],
                {
                    "project_id": project_id,
                    "summary": "加入性能对比",
                    "icon_url": "https://cdn.example.com/new-project.png",
                },
                owner_context,
            )
            assert updated["project"]["summary"] == "加入性能对比"
            assert updated["project"]["icon_url"] == "https://cdn.example.com/new-project.png"

            cleared = invoke_project_tool(
                tools[6],
                {"project_id": project_id, "clear_icon": True},
                owner_context,
            )
            assert cleared["project"]["icon_url"] is None

            confirmation = invoke_project_tool(
                tools[7],
                {"project_id": project_id, "confirmed": False},
                owner_context,
            )
            assert confirmation == {
                "ok": True,
                "status": "confirmation_required",
                "project": {"id": project_id, "title": "MPS 实测"},
            }
            assert db.scalar(select(func.count()).select_from(Project)) == 1

            deleted = invoke_project_tool(
                tools[7],
                {"project_id": project_id, "confirmed": True},
                owner_context,
            )
            assert deleted == {
                "ok": True,
                "status": "deleted",
                "project_id": project_id,
            }
            assert db.scalar(select(func.count()).select_from(Project)) == 0
    finally:
        asyncio.run(client.aclose())
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_project_tools_return_safe_context_error() -> None:
    client, tools = build_tools()

    try:
        unavailable = invoke_project_tool(
            tools[3],
            {
                "title": "标题",
                "type": "知识",
                "audience": "观众",
                "summary": "简介",
                "confirmed": False,
            },
            None,
        )
        assert unavailable == {
            "ok": False,
            "error": {
                "code": "project_context_unavailable",
                "message": "Authenticated project context is unavailable",
            },
        }
    finally:
        asyncio.run(client.aclose())


def test_inspiration_tools_persist_provenance_manage_links_and_require_delete_confirmation() -> (
    None
):
    register_models()
    engine = create_database_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    client, tools = build_tools()
    try:
        with factory() as db:
            owner = add_user(db, "idea-tool-owner")
            other = add_user(db, "idea-tool-other")
            now = utc_now()
            conversation = AgentConversation(
                user_id=owner.id,
                title="灵感对话",
                summary_through_sequence=0,
                next_sequence=2,
                created_at=now,
                updated_at=now,
            )
            message = AgentMessage(
                conversation=conversation,
                turn_id=uuid4(),
                sequence=1,
                item_type="message",
                role="user",
                payload_ciphertext="encrypted-test-payload",
                created_at=now,
            )
            project = Project(
                user_id=owner.id,
                title="MPS 系列",
                type="科技数码",
                audience="Mac 用户",
                summary="本地推理实测",
                created_at=now,
                updated_at=now,
            )
            db.add_all([conversation, message, project])
            db.commit()
            context = AgentRunContext(
                db=db,
                user_id=owner.id,
                conversation_id=conversation.id,
                source_message_id=message.id,
            )
            other_context = AgentRunContext(db=db, user_id=other.id)
            forged_context = AgentRunContext(
                db=db,
                user_id=other.id,
                conversation_id=conversation.id,
                source_message_id=message.id,
            )

            created = invoke_project_tool(
                tools[8],
                {
                    "title": "MPS 速度对比",
                    "content": "测试 MPS 与 CPU 的转写速度",
                    "project_ids": [str(project.id)],
                },
                context,
            )

            assert created["ok"] is True
            assert created["status"] == "created"
            inspiration_id = created["inspiration"]["id"]
            assert created["inspiration"]["source_type"] == "agent"
            assert created["inspiration"]["source_conversation_id"] == str(conversation.id)
            assert created["inspiration"]["source_message_id"] == str(message.id)
            assert db.scalar(select(func.count()).select_from(Inspiration)) == 1

            listed = invoke_project_tool(
                tools[9],
                {"query": "CPU"},
                context,
            )
            assert listed["total"] == 1
            assert listed["inspirations"][0]["id"] == inspiration_id
            assert (
                invoke_project_tool(
                    tools[9],
                    {},
                    other_context,
                )["total"]
                == 0
            )
            forged = invoke_project_tool(
                tools[8],
                {"content": "伪造其他用户的来源"},
                forged_context,
            )
            assert forged["error"]["code"] == "invalid_inspiration"

            hidden = invoke_project_tool(
                tools[10],
                {"inspiration_id": inspiration_id},
                other_context,
            )
            assert hidden["error"]["code"] == "inspiration_not_found"

            updated = invoke_project_tool(
                tools[11],
                {
                    "inspiration_id": inspiration_id,
                    "status": "developing",
                    "content": "加入温度和耗电对比",
                },
                context,
            )
            assert updated["inspiration"]["status"] == "developing"

            removed = invoke_project_tool(
                tools[14],
                {
                    "inspiration_id": inspiration_id,
                    "project_id": str(project.id),
                },
                context,
            )
            assert removed["status"] == "removed"
            added = invoke_project_tool(
                tools[13],
                {
                    "inspiration_id": inspiration_id,
                    "project_id": str(project.id),
                },
                context,
            )
            assert added["status"] == "added"

            preview = invoke_project_tool(
                tools[12],
                {"inspiration_id": inspiration_id, "confirmed": False},
                context,
            )
            assert preview["status"] == "confirmation_required"
            assert preview["inspiration"] == {
                "id": inspiration_id,
                "title": "MPS 速度对比",
            }
            assert db.scalar(select(func.count()).select_from(Inspiration)) == 1

            deleted = invoke_project_tool(
                tools[12],
                {"inspiration_id": inspiration_id, "confirmed": True},
                context,
            )
            assert deleted == {
                "ok": True,
                "status": "deleted",
                "inspiration_id": inspiration_id,
            }
            assert db.scalar(select(func.count()).select_from(Inspiration)) == 0
    finally:
        asyncio.run(client.aclose())
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_project_tool_links_inspirations_and_previews_orphan_cascade() -> None:
    register_models()
    engine = create_database_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    client, tools = build_tools()
    try:
        with factory() as db:
            owner = add_user(db, "linked-project-tool")
            now = utc_now()
            inspiration = Inspiration(
                user_id=owner.id,
                title="待转项目",
                content="把灵感推进成项目",
                status="inbox",
                source_type="manual",
                created_at=now,
                updated_at=now,
            )
            db.add(inspiration)
            db.commit()
            context = AgentRunContext(db=db, user_id=owner.id)
            arguments = {
                "title": "灵感项目",
                "type": "知识",
                "audience": "创作者",
                "summary": "从现有灵感创建",
                "inspiration_ids": [str(inspiration.id)],
                "confirmed": False,
            }

            preview = invoke_project_tool(tools[3], arguments, context)

            assert preview["status"] == "confirmation_required"
            assert preview["inspirations"] == [{"id": str(inspiration.id), "title": "待转项目"}]
            created = invoke_project_tool(
                tools[3],
                {**arguments, "confirmed": True},
                context,
            )
            project_id = created["project"]["id"]
            db.refresh(inspiration)
            assert [str(project.id) for project in inspiration.projects] == [project_id]

            delete_preview = invoke_project_tool(
                tools[7],
                {"project_id": project_id, "confirmed": False},
                context,
            )
            assert delete_preview["status"] == "confirmation_required"
            assert delete_preview["orphaned_inspirations"] == [
                {"id": str(inspiration.id), "title": "待转项目"}
            ]

            deleted = invoke_project_tool(
                tools[7],
                {
                    "project_id": project_id,
                    "confirmed": True,
                    "delete_orphan_inspirations": True,
                },
                context,
            )
            assert deleted["status"] == "deleted"
            assert db.get(Inspiration, inspiration.id) is None
            assert db.get(Project, UUID(project_id)) is None
    finally:
        asyncio.run(client.aclose())
        Base.metadata.drop_all(engine)
        engine.dispose()
