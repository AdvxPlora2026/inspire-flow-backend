import asyncio

import httpx

from inspire_flow_backend.schemas.advisory import BrandAdvisoryContext
from inspire_flow_backend.services.agent.runtime import (
    AgentRuntime,
    _normalize_openai_base_url,
)


def test_normalize_openai_base_url_strips_chat_completions_endpoint() -> None:
    assert (
        _normalize_openai_base_url(
            "https://model.example/v1/chat/completions",
        )
        == "https://model.example/v1"
    )


def test_normalize_openai_base_url_preserves_api_root() -> None:
    assert _normalize_openai_base_url("https://model.example/v1/") == "https://model.example/v1"


class ClosableConversationAgent:
    def __init__(self) -> None:
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1


class ClosableModelClient:
    def __init__(self) -> None:
        self.close_count = 0

    async def close(self) -> None:
        self.close_count += 1


class CountingAsyncClient(httpx.AsyncClient):
    def __init__(self) -> None:
        super().__init__(
            transport=httpx.MockTransport(lambda request: httpx.Response(500, request=request))
        )
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1
        await super().aclose()


class FakeAdvisor:
    async def analyze(self, context: BrandAdvisoryContext):
        del context
        raise AssertionError("not called")


def test_runtime_closes_shared_outbound_and_model_clients_exactly_once() -> None:
    conversation = ClosableConversationAgent()
    model_client = ClosableModelClient()
    outbound = CountingAsyncClient()
    runtime = AgentRuntime(
        conversation_agent=conversation,
        compactor=object(),
        memory_extractor=object(),
        project_draft_generator=object(),
        brand_advisor=FakeAdvisor(),
        _http_client=outbound,
        _model_client=model_client,
    )

    asyncio.run(runtime.aclose())
    asyncio.run(runtime.aclose())

    assert conversation.close_count == 1
    assert outbound.close_count == 1
    assert outbound.is_closed is True
    assert model_client.close_count == 1
