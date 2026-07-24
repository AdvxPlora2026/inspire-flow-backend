import httpx
from agents import FunctionTool

from inspire_flow_backend.services.agent.contracts import (
    AgentToolSettings,
    Clock,
    HostResolver,
)
from inspire_flow_backend.services.agent.func.create_project import (
    build_create_project_tool,
)
from inspire_flow_backend.services.agent.func.current_datetime import (
    build_current_datetime_tool,
)
from inspire_flow_backend.services.agent.func.delete_project import (
    build_delete_project_tool,
)
from inspire_flow_backend.services.agent.func.fetch_webpage import (
    build_fetch_webpage_tool,
)
from inspire_flow_backend.services.agent.func.get_project import (
    build_get_project_tool,
)
from inspire_flow_backend.services.agent.func.list_projects import (
    build_list_projects_tool,
)
from inspire_flow_backend.services.agent.func.search_website import (
    build_search_website_tool,
)
from inspire_flow_backend.services.agent.func.update_project import (
    build_update_project_tool,
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
    return [
        build_current_datetime_tool(clock=clock),
        build_search_website_tool(
            search_service=search_service,
            settings=settings,
        ),
        build_fetch_webpage_tool(
            fetcher=fetcher,
            settings=settings,
        ),
        build_create_project_tool(),
        build_list_projects_tool(),
        build_get_project_tool(),
        build_update_project_tool(),
        build_delete_project_tool(),
    ]
