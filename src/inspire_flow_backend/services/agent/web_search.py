import json
import re
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from inspire_flow_backend.services.agent.contracts import (
    AgentToolError,
    AgentToolSettings,
    SearchResponse,
    SearchResult,
)

DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
_SEARCH_UNAVAILABLE_MESSAGE = "Search provider unavailable"
_DUCKDUCKGO_CHALLENGE_MARKERS = (
    "unfortunately, bots use duckduckgo too",
    "anomaly-modal",
    "challenge-form",
)
_LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


class SearchProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def search(self, query: str, limit: int) -> list[SearchResult]: ...


class WebSearchService:
    def __init__(
        self,
        *,
        primary: SearchProvider,
        fallback: SearchProvider,
        settings: AgentToolSettings,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._settings = settings

    async def search(self, query: str, limit: int) -> SearchResponse:
        normalized_query = " ".join(query.split())
        if not normalized_query or len(normalized_query) > self._settings.max_query_characters:
            raise AgentToolError("invalid_query", "Search query is empty or too long")
        if limit < 1 or limit > self._settings.max_search_results:
            raise AgentToolError(
                "invalid_result_count",
                "Search result count is outside the supported range",
            )

        try:
            results = await self._primary.search(normalized_query, limit)
        except AgentToolError as error:
            if error.code != "search_unavailable":
                raise
        else:
            if results:
                return SearchResponse(
                    query=normalized_query,
                    provider=self._primary.name,
                    results=results,
                )

        results = await self._fallback.search(normalized_query, limit)
        return SearchResponse(
            query=normalized_query,
            provider=self._fallback.name,
            results=results,
        )


class DuckDuckGoHtmlSearchProvider:
    name = "duckduckgo"

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: AgentToolSettings,
    ) -> None:
        self._http_client = http_client
        self._settings = settings

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        body = await _request_provider_bytes(
            self._http_client,
            DUCKDUCKGO_HTML_URL,
            params={"q": query},
            settings=self._settings,
        )
        document = body.decode("utf-8", errors="replace")
        lower_document = document.lower()
        if any(marker in lower_document for marker in _DUCKDUCKGO_CHALLENGE_MARKERS):
            raise _search_unavailable()

        parser = _DuckDuckGoResultParser()
        parser.feed(document)
        parser.close()

        results = parser.results(limit)
        if not results:
            raise _search_unavailable()
        return results


class MediaWikiSearchProvider:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: AgentToolSettings,
        *,
        language: str = "zh",
    ) -> None:
        if not _LANGUAGE_CODE_PATTERN.fullmatch(language):
            raise ValueError("language must be a valid MediaWiki language code")
        self._http_client = http_client
        self._settings = settings
        self._language = language

    @property
    def name(self) -> str:
        return f"mediawiki_{self._language}"

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        endpoint = f"https://{self._language}.wikipedia.org/w/api.php"
        body = await _request_provider_bytes(
            self._http_client,
            endpoint,
            params={
                "action": "query",
                "list": "search",
                "format": "json",
                "formatversion": "2",
                "srsearch": query,
                "srlimit": limit,
            },
            settings=self._settings,
        )
        try:
            payload = json.loads(body)
            records = payload["query"]["search"]
            if not isinstance(records, list):
                raise TypeError
            return [self._map_record(record) for record in records[:limit]]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise _search_unavailable() from error

    def _map_record(self, record: object) -> SearchResult:
        if not isinstance(record, dict):
            raise TypeError
        title = record.get("title")
        snippet = record.get("snippet", "")
        if not isinstance(title, str) or not title.strip() or not isinstance(snippet, str):
            raise TypeError
        normalized_title = _normalize_text(title)
        article_name = quote(normalized_title.replace(" ", "_"), safe="()_,-")
        return SearchResult(
            title=normalized_title,
            url=f"https://{self._language}.wikipedia.org/wiki/{article_name}",
            snippet=_html_to_text(snippet),
        )


async def _request_provider_bytes(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str | int],
    settings: AgentToolSettings,
) -> bytes:
    try:
        async with client.stream(
            "GET",
            url,
            params=params,
            headers={"User-Agent": settings.user_agent},
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
        ) as response:
            if response.status_code != httpx.codes.OK:
                raise _search_unavailable()
            chunks: list[bytes] = []
            byte_count = 0
            async for chunk in response.aiter_bytes():
                byte_count += len(chunk)
                if byte_count > settings.max_search_response_bytes:
                    raise _search_unavailable()
                chunks.append(chunk)
    except AgentToolError:
        raise
    except httpx.HTTPError as error:
        raise _search_unavailable() from error
    return b"".join(chunks)


class _PendingSearchResult:
    def __init__(self, href: str) -> None:
        self.href = href
        self.title_parts: list[str] = []
        self.snippet_parts: list[str] = []


class _DuckDuckGoResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._pending: list[_PendingSearchResult] = []
        self._active_parts: list[str] | None = None
        self._active_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self._active_parts is not None:
            self._active_depth += 1
            return

        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if "result__a" in classes:
            candidate = _PendingSearchResult(attributes.get("href") or "")
            self._pending.append(candidate)
            self._active_parts = candidate.title_parts
            self._active_depth = 1
        elif "result__snippet" in classes and self._pending:
            self._active_parts = self._pending[-1].snippet_parts
            self._active_depth = 1

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self._active_parts is not None:
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        del tag
        if self._active_parts is None:
            return
        self._active_depth -= 1
        if self._active_depth == 0:
            self._active_parts = None

    def handle_data(self, data: str) -> None:
        if self._active_parts is not None:
            self._active_parts.append(data)

    def results(self, limit: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for candidate in self._pending:
            title = _normalize_text("".join(candidate.title_parts))
            url = _normalize_result_url(candidate.href)
            if not title or url is None or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=_normalize_text("".join(candidate.snippet_parts)),
                )
            )
            if len(results) == limit:
                break
        return results


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _html_to_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value)
    parser.close()
    return _normalize_text("".join(parser.parts))


def _normalize_result_url(href: str) -> str | None:
    candidate = href.strip()
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    parsed = urlsplit(candidate)
    query = parse_qs(parsed.query)
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    is_duckduckgo = hostname == "duckduckgo.com" or hostname.endswith(".duckduckgo.com")
    if is_duckduckgo and query.get("uddg"):
        candidate = query["uddg"][0]
        parsed = urlsplit(candidate)
    try:
        port = parsed.port
    except ValueError:
        return None
    del port
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return candidate


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _search_unavailable() -> AgentToolError:
    return AgentToolError("search_unavailable", _SEARCH_UNAVAILABLE_MESSAGE)
