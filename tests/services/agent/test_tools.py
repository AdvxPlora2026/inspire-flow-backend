import asyncio
import importlib
import json
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from agents.tool_context import ToolContext

from inspire_flow_backend.services.agent.contracts import (
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


async def invoke_tool_async(tool, arguments: dict[str, object]) -> str:
    arguments_json = json.dumps(arguments)
    context = ToolContext(
        context=None,
        tool_name=tool.name,
        tool_call_id="test-call",
        tool_arguments=arguments_json,
    )
    return await tool.on_invoke_tool(context, arguments_json)


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
