from agents import FunctionTool, function_tool

from inspire_flow_backend.services.agent.contracts import (
    AgentToolError,
    AgentToolSettings,
)
from inspire_flow_backend.services.agent.func._shared import (
    error_json,
    timeout_error_formatter,
)
from inspire_flow_backend.services.agent.web_fetch import WebPageFetcher


def build_fetch_webpage_tool(
    *,
    fetcher: WebPageFetcher,
    settings: AgentToolSettings,
) -> FunctionTool:
    @function_tool(
        name_override="fetch_webpage",
        failure_error_function=None,
        timeout=settings.tool_timeout_seconds,
        timeout_error_function=timeout_error_formatter(
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
            return error_json(error)
        return result.model_dump_json(exclude_none=True)

    return fetch_webpage
