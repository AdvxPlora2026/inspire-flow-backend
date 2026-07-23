from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from agents import FunctionTool, RunContextWrapper, function_tool

from inspire_flow_backend.services.agent.contracts import (
    AgentToolError,
    AgentToolSettings,
    Clock,
    DateTimeResult,
    HostResolver,
    ToolErrorBody,
    ToolErrorResult,
)
from inspire_flow_backend.services.agent.web_fetch import (
    WebPageFetcher,
    resolve_hostname,
)
from inspire_flow_backend.services.agent.web_search import (
    DuckDuckGoHtmlSearchProvider,
    MediaWikiSearchProvider,
    WebSearchService,
)


def get_current_datetime(
    timezone_name: str,
    clock: Clock,
) -> DateTimeResult:
    try:
        timezone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise AgentToolError(
            "invalid_timezone",
            "Unknown IANA timezone",
        ) from error

    current = clock()
    if current.tzinfo is None or current.utcoffset() is None:
        raise RuntimeError("Agent clock must return a timezone-aware datetime")
    localized = current.astimezone(timezone)
    return DateTimeResult(
        timezone=timezone.key,
        iso_datetime=localized.isoformat(),
        unix_timestamp=int(current.timestamp()),
    )


def _error_json(error: AgentToolError) -> str:
    return ToolErrorResult(
        error=ToolErrorBody(
            code=error.code,
            message=error.message,
        )
    ).model_dump_json()


def _timeout_error_formatter(code: str, message: str):
    def format_timeout(
        context: RunContextWrapper[Any],
        error: Exception,
    ) -> str:
        del context, error
        return _error_json(AgentToolError(code, message))

    return format_timeout


def build_agent_tools(
    *,
    http_client: httpx.AsyncClient,
    settings: AgentToolSettings,
    clock: Clock,
    resolver: HostResolver | None,
) -> list[FunctionTool]:
    search_service = WebSearchService(
        primary=DuckDuckGoHtmlSearchProvider(http_client, settings),
        fallback=MediaWikiSearchProvider(http_client, settings),
        settings=settings,
    )
    fetcher = WebPageFetcher(
        http_client,
        settings,
        resolver=resolver or resolve_hostname,
    )
    default_search_results = settings.default_search_results

    @function_tool(
        name_override="current_datetime",
        failure_error_function=None,
    )
    def current_datetime(timezone_name: str = "UTC") -> str:
        """Return the current date and time in an IANA timezone.

        Args:
            timezone_name: IANA timezone such as UTC or Asia/Shanghai.
        """
        try:
            return get_current_datetime(timezone_name, clock).model_dump_json()
        except AgentToolError as error:
            return _error_json(error)

    @function_tool(
        name_override="search_website",
        failure_error_function=None,
        timeout=settings.tool_timeout_seconds,
        timeout_error_function=_timeout_error_formatter(
            "search_unavailable",
            "Search tool timed out",
        ),
    )
    async def search_website(
        query: str,
        max_results: int = default_search_results,
    ) -> str:
        """Search the public web without requiring an API key.

        Args:
            query: Search terms.
            max_results: Maximum number of results to return.
        """
        try:
            result = await search_service.search(query, max_results)
        except AgentToolError as error:
            return _error_json(error)
        return result.model_dump_json(exclude_none=True)

    @function_tool(
        name_override="fetch_webpage",
        failure_error_function=None,
        timeout=settings.tool_timeout_seconds,
        timeout_error_function=_timeout_error_formatter(
            "fetch_unavailable",
            "Webpage fetch tool timed out",
        ),
    )
    async def fetch_webpage(url: str) -> str:
        """Fetch readable text from a public HTTP or HTTPS page.

        Args:
            url: Public webpage URL.
        """
        try:
            result = await fetcher.fetch(url)
        except AgentToolError as error:
            return _error_json(error)
        return result.model_dump_json(exclude_none=True)

    return [current_datetime, search_website, fetch_webpage]
