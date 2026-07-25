from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from agents import FunctionTool, RunContextWrapper, function_tool
from pydantic import ValidationError

from inspire_flow_backend.core.errors import (
    AgentRunFailedError,
    BrandNotFoundError,
    ProjectNotFoundError,
)
from inspire_flow_backend.schemas.advisory import BrandAdvisoryRequest
from inspire_flow_backend.services import advisory as advisory_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    advisory_unavailable_error_json,
    brand_context_error_json,
    brand_not_found_error_json,
    invalid_advisory_request_error_json,
    project_not_found_error_json,
    success_json,
)

if TYPE_CHECKING:
    from inspire_flow_backend.services.agent.brand_advisor import BrandAdvisor


def build_analyze_brand_project_tool(
    *,
    brand_advisor: BrandAdvisor | None,
) -> FunctionTool:
    @function_tool(
        name_override="analyze_brand_project",
        failure_error_function=None,
    )
    async def analyze_brand_project(
        ctx: RunContextWrapper[AgentRunContext | None],
        brand_id: UUID,
        project_brief: str,
        project_id: UUID | None = None,
        market: str = "China mainland",
        focus_topics: list[str] | None = None,
        lookback_days: int = 7,
    ) -> str:
        """Research current topics and advise an authenticated brand project.

        Args:
            brand_id: Brand UUID selected from the user's memberships.
            project_brief: Concrete project facts, goals, audience, and constraints.
            project_id: Optional project UUID owned by the authenticated user.
            market: Free-form market context.
            focus_topics: Optional list of up to five research topics.
            lookback_days: Current-topic window from 1 to 30 days.
        """
        context = ctx.context
        if context is None:
            return brand_context_error_json()
        try:
            payload = BrandAdvisoryRequest(
                project_brief=project_brief,
                project_id=project_id,
                market=market,
                focus_topics=focus_topics or [],
                lookback_days=lookback_days,
            )
        except ValidationError:
            return invalid_advisory_request_error_json()
        if brand_advisor is None:
            return advisory_unavailable_error_json()
        try:
            report = await advisory_service.analyze_brand_project(
                context.db,
                context.user_id,
                brand_id,
                payload,
                brand_advisor,
            )
        except BrandNotFoundError:
            return brand_not_found_error_json()
        except ProjectNotFoundError:
            return project_not_found_error_json()
        except AgentRunFailedError:
            return advisory_unavailable_error_json()
        return success_json(report=report.model_dump(mode="json"))

    return analyze_brand_project
