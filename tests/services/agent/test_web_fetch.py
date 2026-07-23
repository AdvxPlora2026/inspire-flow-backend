import asyncio
from collections.abc import Awaitable, Callable

import httpx
import pytest

from inspire_flow_backend.services.agent.contracts import AgentToolError, AgentToolSettings
from inspire_flow_backend.services.agent.web_fetch import (
    WebPageFetcher,
    validate_public_url,
)

PUBLIC_IPV4 = "93.184.216.34"
Resolver = Callable[[str], Awaitable[set[str]]]


def run(coroutine):
    return asyncio.run(coroutine)


def resolver_for(*addresses: str) -> Resolver:
    async def resolver(hostname: str) -> set[str]:
        del hostname
        return set(addresses)

    return resolver


def test_url_policy_accepts_public_http_url_and_removes_fragment() -> None:
    resolved_hosts: list[str] = []

    async def resolver(hostname: str) -> set[str]:
        resolved_hosts.append(hostname)
        return {PUBLIC_IPV4}

    result = run(
        validate_public_url(
            "https://Example.COM:443/articles?q=python#section",
            resolver,
        )
    )

    assert result == "https://Example.COM:443/articles?q=python"
    assert resolved_hosts == ["example.com"]


@pytest.mark.parametrize(
    "url",
    [
        "",
        "/relative",
        "ftp://example.com/file",
        "https://",
        "https://example.com:invalid/",
        "https://exa mple.com/",
        "https://example.com\\@127.0.0.1/",
    ],
)
def test_url_policy_rejects_malformed_or_unsupported_urls(url: str) -> None:
    with pytest.raises(AgentToolError) as captured:
        run(validate_public_url(url, resolver_for(PUBLIC_IPV4)))

    assert captured.value.code == "invalid_url"


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@example.com/",
        "https://user@example.com/",
        "https://example.com:8080/",
    ],
)
def test_url_policy_rejects_credentials_and_unsafe_ports(url: str) -> None:
    with pytest.raises(AgentToolError) as captured:
        run(validate_public_url(url, resolver_for(PUBLIC_IPV4)))

    assert captured.value.code == "unsafe_url"


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "224.0.0.1",
        "192.0.2.1",
        "0.0.0.0",
        "100.64.0.1",
        "::1",
        "fe80::1",
        "fec0::1",
        "ff02::1",
    ],
)
def test_url_policy_rejects_non_global_ip_literals(address: str) -> None:
    host = f"[{address}]" if ":" in address else address

    with pytest.raises(AgentToolError) as captured:
        run(validate_public_url(f"http://{host}/", resolver_for(PUBLIC_IPV4)))

    assert captured.value.code == "unsafe_url"


def test_url_policy_requires_every_dns_answer_to_be_global() -> None:
    resolver = resolver_for(PUBLIC_IPV4, "127.0.0.1")

    with pytest.raises(AgentToolError) as captured:
        run(validate_public_url("https://example.com/", resolver))

    assert captured.value.code == "unsafe_url"


def test_url_policy_rejects_empty_dns_answer() -> None:
    with pytest.raises(AgentToolError) as captured:
        run(validate_public_url("https://example.com/", resolver_for()))

    assert captured.value.code == "unsafe_url"


def test_fetcher_extracts_visible_html_and_title() -> None:
    requests: list[httpx.Request] = []
    page = """
    <!doctype html>
    <html>
      <head>
        <title> Example &amp; News </title>
        <style>body { display: none }</style>
      </head>
      <body>
        <h1>Hello <em>world</em>.</h1>
        <script>secret()</script>
        <noscript>enable scripts</noscript>
        <template>template secret</template>
        <svg><text>vector secret</text></svg>
        <p>Visible paragraph.</p>
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            text=page,
            headers={"Content-Type": "text/html; charset=utf-8"},
            request=request,
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher = WebPageFetcher(
                client,
                AgentToolSettings(),
                resolver=resolver_for(PUBLIC_IPV4),
            )
            return await fetcher.fetch("https://example.com/article#intro")

    result = run(scenario())

    assert len(requests) == 1
    assert requests[0].url == httpx.URL("https://example.com/article")
    assert requests[0].headers["User-Agent"] == "InspireFlowBackend/0.1"
    assert result.model_dump(exclude_none=True) == {
        "ok": True,
        "url": "https://example.com/article",
        "content_type": "text/html",
        "title": "Example & News",
        "text": "Hello world. Visible paragraph.",
        "truncated": False,
    }


@pytest.mark.parametrize(
    ("content_type", "body", "expected_text"),
    [
        ("text/plain; charset=iso-8859-1", "café".encode("iso-8859-1"), "café"),
        ("application/json", b'{"ok": true}', '{"ok": true}'),
        ("application/xhtml+xml; charset=utf-8", b"<main>XHTML body</main>", "XHTML body"),
    ],
)
def test_fetcher_supports_bounded_text_content(
    content_type: str,
    body: bytes,
    expected_text: str,
) -> None:
    async def scenario():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=body,
                headers={"Content-Type": content_type},
                request=request,
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            fetcher = WebPageFetcher(
                client,
                AgentToolSettings(),
                resolver=resolver_for(PUBLIC_IPV4),
            )
            return await fetcher.fetch("https://example.com/content")

    result = run(scenario())

    assert result.text == expected_text
    assert result.truncated is False


def test_fetcher_validates_every_redirect_before_requesting_it() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={"Location": "/final"},
                request=request,
            )
        return httpx.Response(
            200,
            text="done",
            headers={"Content-Type": "text/plain"},
            request=request,
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher = WebPageFetcher(
                client,
                AgentToolSettings(),
                resolver=resolver_for(PUBLIC_IPV4),
            )
            return await fetcher.fetch("https://example.com/start")

    result = run(scenario())

    assert [str(request.url) for request in requests] == [
        "https://example.com/start",
        "https://example.com/final",
    ]
    assert result.url == "https://example.com/final"
    assert result.text == "done"


def test_fetcher_rejects_unsafe_redirect_without_requesting_destination() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1/admin"},
            request=request,
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher = WebPageFetcher(
                client,
                AgentToolSettings(),
                resolver=resolver_for(PUBLIC_IPV4),
            )
            await fetcher.fetch("https://example.com/start")

    with pytest.raises(AgentToolError) as captured:
        run(scenario())

    assert captured.value.code == "unsafe_url"
    assert len(requests) == 1


def test_fetcher_enforces_redirect_limit() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        next_path = "/second" if request.url.path == "/first" else "/third"
        return httpx.Response(302, headers={"Location": next_path}, request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher = WebPageFetcher(
                client,
                AgentToolSettings(max_redirects=1),
                resolver=resolver_for(PUBLIC_IPV4),
            )
            await fetcher.fetch("https://example.com/first")

    with pytest.raises(AgentToolError) as captured:
        run(scenario())

    assert captured.value.code == "redirect_limit"
    assert [request.url.path for request in requests] == ["/first", "/second"]


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (
            {"status_code": 200, "headers": {"Content-Type": "image/png"}, "content": b"png"},
            "unsupported_content_type",
        ),
        (
            {"status_code": 503, "headers": {"Content-Type": "text/plain"}, "content": b"down"},
            "fetch_unavailable",
        ),
        (
            {"status_code": 302, "headers": {}, "content": b""},
            "fetch_unavailable",
        ),
    ],
)
def test_fetcher_maps_unsupported_and_failed_responses(
    response: dict[str, object],
    expected_code: str,
) -> None:
    async def scenario() -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(request=request, **response))
        async with httpx.AsyncClient(transport=transport) as client:
            fetcher = WebPageFetcher(
                client,
                AgentToolSettings(),
                resolver=resolver_for(PUBLIC_IPV4),
            )
            await fetcher.fetch("https://example.com/content")

    with pytest.raises(AgentToolError) as captured:
        run(scenario())

    assert captured.value.code == expected_code


def test_fetcher_rejects_oversized_decoded_response() -> None:
    async def scenario() -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"x" * 65,
                headers={"Content-Type": "text/plain"},
                request=request,
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            fetcher = WebPageFetcher(
                client,
                AgentToolSettings(max_fetch_response_bytes=64),
                resolver=resolver_for(PUBLIC_IPV4),
            )
            await fetcher.fetch("https://example.com/large")

    with pytest.raises(AgentToolError) as captured:
        run(scenario())

    assert captured.value.code == "response_too_large"


def test_fetcher_truncates_readable_output_at_character_limit() -> None:
    async def scenario():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text="abcdefghij",
                headers={"Content-Type": "text/plain"},
                request=request,
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            fetcher = WebPageFetcher(
                client,
                AgentToolSettings(max_fetch_output_characters=6),
                resolver=resolver_for(PUBLIC_IPV4),
            )
            return await fetcher.fetch("https://example.com/text")

    result = run(scenario())

    assert result.text == "abcdef"
    assert result.truncated is True


def test_fetcher_falls_back_to_utf8_for_unknown_charset() -> None:
    async def scenario():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content="你好".encode(),
                headers={"Content-Type": "text/plain; charset=not-a-codec"},
                request=request,
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            fetcher = WebPageFetcher(
                client,
                AgentToolSettings(),
                resolver=resolver_for(PUBLIC_IPV4),
            )
            return await fetcher.fetch("https://example.com/text")

    result = run(scenario())

    assert result.text == "你好"


def test_fetcher_maps_httpx_errors_without_exposing_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret upstream detail", request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher = WebPageFetcher(
                client,
                AgentToolSettings(),
                resolver=resolver_for(PUBLIC_IPV4),
            )
            await fetcher.fetch("https://example.com/")

    with pytest.raises(AgentToolError) as captured:
        run(scenario())

    assert captured.value.code == "fetch_unavailable"
    assert captured.value.message == "Webpage fetch unavailable"
