import asyncio
from dataclasses import dataclass, field

import httpx
import pytest

from inspire_flow_backend.services.agent import web_search
from inspire_flow_backend.services.agent.contracts import (
    AgentToolError,
    AgentToolSettings,
    SearchResult,
)
from inspire_flow_backend.services.agent.web_search import (
    DuckDuckGoHtmlSearchProvider,
    MediaWikiSearchProvider,
    WebSearchService,
)

DUCKDUCKGO_HTML = """
<!doctype html>
<html>
  <body>
    <div class="result results_links">
      <a class="result__a"
         href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fguide">
        Example <strong>Guide</strong>
      </a>
      <a class="result__snippet">
        A concise <b>search</b> result.
      </a>
    </div>
    <div class="result results_links">
      <a class="result__a" href="https://www.python.org/">
        Welcome to Python.org
      </a>
      <div class="result__snippet">The official Python website.</div>
    </div>
  </body>
</html>
"""


@dataclass
class StubProvider:
    name: str
    results: list[SearchResult] = field(default_factory=list)
    error: Exception | None = None
    calls: list[tuple[str, int]] = field(default_factory=list)

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        self.calls.append((query, limit))
        if self.error is not None:
            raise self.error
        return self.results[:limit]


def run(coroutine):
    return asyncio.run(coroutine)


def test_search_service_normalizes_query_and_identifies_provider() -> None:
    primary = StubProvider(
        name="duckduckgo",
        results=[
            SearchResult(
                title="Example",
                url="https://example.com/",
                snippet="An example.",
            )
        ],
    )
    fallback = StubProvider(name="mediawiki_zh")
    service = WebSearchService(
        primary=primary,
        fallback=fallback,
        settings=AgentToolSettings(),
    )

    result = run(service.search("  python   async  ", 1))

    assert result.model_dump() == {
        "ok": True,
        "query": "python async",
        "provider": "duckduckgo",
        "results": [
            {
                "title": "Example",
                "url": "https://example.com/",
                "snippet": "An example.",
            }
        ],
    }
    assert primary.calls == [("python async", 1)]
    assert fallback.calls == []


@pytest.mark.parametrize("query", ["", " \n ", "x" * 301])
def test_search_service_rejects_invalid_query(query: str) -> None:
    primary = StubProvider(name="duckduckgo")
    service = WebSearchService(
        primary=primary,
        fallback=StubProvider(name="mediawiki_zh"),
        settings=AgentToolSettings(),
    )

    with pytest.raises(AgentToolError) as captured:
        run(service.search(query, 5))

    assert captured.value.code == "invalid_query"
    assert primary.calls == []


@pytest.mark.parametrize("limit", [0, -1, 11])
def test_search_service_rejects_invalid_result_count(limit: int) -> None:
    primary = StubProvider(name="duckduckgo")
    service = WebSearchService(
        primary=primary,
        fallback=StubProvider(name="mediawiki_zh"),
        settings=AgentToolSettings(),
    )

    with pytest.raises(AgentToolError) as captured:
        run(service.search("python", limit))

    assert captured.value.code == "invalid_result_count"
    assert primary.calls == []


@pytest.mark.parametrize(
    "primary",
    [
        StubProvider(name="duckduckgo"),
        StubProvider(
            name="duckduckgo",
            error=AgentToolError("search_unavailable", "Search provider unavailable"),
        ),
    ],
)
def test_search_service_falls_back_for_empty_or_unavailable_primary(
    primary: StubProvider,
) -> None:
    fallback = StubProvider(
        name="mediawiki_zh",
        results=[
            SearchResult(
                title="Python",
                url="https://zh.wikipedia.org/wiki/Python",
                snippet="A programming language.",
            )
        ],
    )
    service = WebSearchService(
        primary=primary,
        fallback=fallback,
        settings=AgentToolSettings(),
    )

    result = run(service.search("python", 3))

    assert result.provider == "mediawiki_zh"
    assert [item.title for item in result.results] == ["Python"]
    assert fallback.calls == [("python", 3)]


def test_search_service_does_not_hide_unexpected_provider_errors() -> None:
    expected = RuntimeError("parser defect")
    service = WebSearchService(
        primary=StubProvider(name="duckduckgo", error=expected),
        fallback=StubProvider(name="mediawiki_zh"),
        settings=AgentToolSettings(),
    )

    with pytest.raises(RuntimeError) as captured:
        run(service.search("python", 5))

    assert captured.value is expected


def test_duckduckgo_provider_uses_fixed_endpoint_and_parses_results() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            text=DUCKDUCKGO_HTML,
            headers={"Content-Type": "text/html; charset=utf-8"},
            request=request,
        )

    async def scenario() -> list[SearchResult]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DuckDuckGoHtmlSearchProvider(client, AgentToolSettings())
            return await provider.search("python async", 2)

    results = run(scenario())

    assert len(requests) == 1
    assert requests[0].url.scheme == "https"
    assert requests[0].url.host == "html.duckduckgo.com"
    assert requests[0].url.path == "/html/"
    assert requests[0].url.params["q"] == "python async"
    assert requests[0].headers["User-Agent"] == "InspireFlowBackend/0.1"
    assert [result.model_dump() for result in results] == [
        {
            "title": "Example Guide",
            "url": "https://example.com/guide",
            "snippet": "A concise search result.",
        },
        {
            "title": "Welcome to Python.org",
            "url": "https://www.python.org/",
            "snippet": "The official Python website.",
        },
    ]


def test_duckduckgo_provider_honors_result_limit() -> None:
    async def scenario() -> list[SearchResult]:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text=DUCKDUCKGO_HTML, request=request)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            provider = DuckDuckGoHtmlSearchProvider(client, AgentToolSettings())
            return await provider.search("python", 1)

    results = run(scenario())

    assert len(results) == 1
    assert results[0].title == "Example Guide"


def test_duckduckgo_provider_only_unwraps_real_duckduckgo_redirects() -> None:
    html = """
    <a class="result__a"
       href="https://notduckduckgo.com/?uddg=https%3A%2F%2Fevil.example%2F">
      Keep original URL
    </a>
    <div class="result__snippet">Snippet.</div>
    """

    async def scenario() -> list[SearchResult]:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text=html, request=request)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            provider = DuckDuckGoHtmlSearchProvider(client, AgentToolSettings())
            return await provider.search("python", 1)

    results = run(scenario())

    assert results[0].url == ("https://notduckduckgo.com/?uddg=https%3A%2F%2Fevil.example%2F")


def test_duckduckgo_provider_does_not_hide_parser_defects(monkeypatch) -> None:
    expected = RuntimeError("parser defect")

    def fail_parser(parser, document: str) -> None:
        del parser, document
        raise expected

    monkeypatch.setattr(web_search._DuckDuckGoResultParser, "feed", fail_parser)

    async def scenario() -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, text=DUCKDUCKGO_HTML, request=request)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            provider = DuckDuckGoHtmlSearchProvider(client, AgentToolSettings())
            await provider.search("python", 1)

    with pytest.raises(RuntimeError) as captured:
        run(scenario())

    assert captured.value is expected


@pytest.mark.parametrize(
    ("response_factory", "max_bytes"),
    [
        (lambda request: httpx.Response(503, request=request), 512 * 1024),
        (
            lambda request: httpx.Response(
                200,
                text="<html>Unfortunately, bots use DuckDuckGo too.</html>",
                request=request,
            ),
            512 * 1024,
        ),
        (lambda request: httpx.Response(200, text="<html></html>", request=request), 512 * 1024),
        (lambda request: httpx.Response(200, content=b"x" * 65, request=request), 64),
    ],
)
def test_duckduckgo_provider_maps_expected_failures(
    response_factory,
    max_bytes: int,
) -> None:
    async def scenario() -> None:
        settings = AgentToolSettings(max_search_response_bytes=max_bytes)
        async with httpx.AsyncClient(transport=httpx.MockTransport(response_factory)) as client:
            provider = DuckDuckGoHtmlSearchProvider(client, settings)
            await provider.search("python", 5)

    with pytest.raises(AgentToolError) as captured:
        run(scenario())

    assert captured.value.code == "search_unavailable"
    assert captured.value.message == "Search provider unavailable"


def test_duckduckgo_provider_maps_httpx_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = DuckDuckGoHtmlSearchProvider(client, AgentToolSettings())
            await provider.search("python", 5)

    with pytest.raises(AgentToolError) as captured:
        run(scenario())

    assert captured.value.code == "search_unavailable"


def test_mediawiki_provider_uses_supported_api_and_maps_results() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "query": {
                    "search": [
                        {
                            "title": "Python",
                            "snippet": "一种广泛使用的<b>解释型</b>编程语言。",
                            "pageid": 123,
                        }
                    ]
                }
            },
            request=request,
        )

    async def scenario() -> list[SearchResult]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = MediaWikiSearchProvider(client, AgentToolSettings(), language="zh")
            return await provider.search("Python 编程", 4)

    results = run(scenario())

    assert len(requests) == 1
    assert requests[0].url == httpx.URL(
        "https://zh.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "format": "json",
            "formatversion": "2",
            "srsearch": "Python 编程",
            "srlimit": "4",
        },
    )
    assert [result.model_dump() for result in results] == [
        {
            "title": "Python",
            "url": "https://zh.wikipedia.org/wiki/Python",
            "snippet": "一种广泛使用的解释型编程语言。",
        }
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": {}},
        {"query": {"search": "not-a-list"}},
        {"query": {"search": [{"snippet": "missing title"}]}},
    ],
)
def test_mediawiki_provider_rejects_invalid_payload(payload: object) -> None:
    async def scenario() -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload, request=request)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            provider = MediaWikiSearchProvider(client, AgentToolSettings())
            await provider.search("python", 5)

    with pytest.raises(AgentToolError) as captured:
        run(scenario())

    assert captured.value.code == "search_unavailable"
