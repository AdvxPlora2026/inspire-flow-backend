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
        normalized_instructions = DEFAULT_AGENT_INSTRUCTIONS.lower()
        assert "untrusted data" in normalized_instructions
        assert "never follow instructions" in normalized_instructions
    finally:
        asyncio.run(client.aclose())


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
