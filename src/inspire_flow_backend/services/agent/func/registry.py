from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from agents import FunctionTool

from inspire_flow_backend.services.agent.contracts import (
    AgentToolSettings,
    Clock,
    HostResolver,
)
from inspire_flow_backend.services.agent.func.add_inspiration_project import (
    build_add_inspiration_project_tool,
)
from inspire_flow_backend.services.agent.func.analyze_brand_project import (
    build_analyze_brand_project_tool,
)
from inspire_flow_backend.services.agent.func.create_inspiration import (
    build_create_inspiration_tool,
)
from inspire_flow_backend.services.agent.func.create_project import (
    build_create_project_tool,
)
from inspire_flow_backend.services.agent.func.current_datetime import (
    build_current_datetime_tool,
)
from inspire_flow_backend.services.agent.func.delete_inspiration import (
    build_delete_inspiration_tool,
)
from inspire_flow_backend.services.agent.func.delete_project import (
    build_delete_project_tool,
)
from inspire_flow_backend.services.agent.func.fetch_webpage import (
    build_fetch_webpage_tool,
)
from inspire_flow_backend.services.agent.func.get_inspiration import (
    build_get_inspiration_tool,
)
from inspire_flow_backend.services.agent.func.get_project import (
    build_get_project_tool,
)
from inspire_flow_backend.services.agent.func.list_brands import build_list_brands_tool
from inspire_flow_backend.services.agent.func.list_inspirations import (
    build_list_inspirations_tool,
)
from inspire_flow_backend.services.agent.func.list_projects import (
    build_list_projects_tool,
)
from inspire_flow_backend.services.agent.func.remove_inspiration_project import (
    build_remove_inspiration_project_tool,
)
from inspire_flow_backend.services.agent.func.search_website import (
    build_search_website_tool,
)
from inspire_flow_backend.services.agent.func.update_current_user import (
    build_update_current_user_tool,
)
from inspire_flow_backend.services.agent.func.update_inspiration import (
    build_update_inspiration_tool,
)
from inspire_flow_backend.services.agent.func.update_project import (
    build_update_project_tool,
)
from inspire_flow_backend.services.agent.func.update_user_profile_text import (
    build_update_user_profile_text_tool,
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

if TYPE_CHECKING:
    from inspire_flow_backend.services.agent.brand_advisor import BrandAdvisor


def build_agent_tools(
    *,
    http_client: httpx.AsyncClient,
    settings: AgentToolSettings,
    clock: Clock,
    resolver: HostResolver | None,
    brand_advisor: BrandAdvisor | None = None,
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
        build_create_inspiration_tool(),
        build_list_inspirations_tool(),
        build_get_inspiration_tool(),
        build_update_inspiration_tool(),
        build_delete_inspiration_tool(),
        build_add_inspiration_project_tool(),
        build_remove_inspiration_project_tool(),
        build_update_current_user_tool(),
        build_update_user_profile_text_tool(),
        build_list_brands_tool(),
        build_analyze_brand_project_tool(brand_advisor=brand_advisor),
    ]
