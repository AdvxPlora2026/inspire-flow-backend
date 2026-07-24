from agents import FunctionTool, function_tool

from inspire_flow_backend.services.agent.contracts import (
    AgentToolError,
    AgentToolSettings,
)
from inspire_flow_backend.services.agent.func._shared import (
    error_json,
    timeout_error_formatter,
)
from inspire_flow_backend.services.agent.web_search import WebSearchService


def build_search_website_tool(
    *,
    search_service: WebSearchService,
    settings: AgentToolSettings,
) -> FunctionTool:
    default_search_results = settings.default_search_results

    @function_tool(
        name_override="search_website",
        failure_error_function=None,
        timeout=settings.tool_timeout_seconds,
        timeout_error_function=timeout_error_formatter(
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
            return error_json(error)
        return result.model_dump_json(exclude_none=True)

    return search_website
