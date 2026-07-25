from agents import FunctionTool, RunContextWrapper, function_tool

from inspire_flow_backend.services import brands as brand_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    brand_context_error_json,
    invalid_advisory_request_error_json,
    success_json,
)


def build_list_brands_tool() -> FunctionTool:
    @function_tool(
        name_override="list_brands",
        failure_error_function=None,
    )
    async def list_brands(
        ctx: RunContextWrapper[AgentRunContext | None],
        limit: int = 50,
        offset: int = 0,
    ) -> str:
        """List brands where the authenticated user is an active member.

        Args:
            limit: Page size from 1 to 100.
            offset: Number of brands to skip.
        """
        context = ctx.context
        if context is None:
            return brand_context_error_json()
        if (
            isinstance(limit, bool)
            or not 1 <= limit <= 100
            or isinstance(offset, bool)
            or offset < 0
        ):
            return invalid_advisory_request_error_json()
        page = brand_service.list_brands(
            context.db,
            context.user_id,
            limit=limit,
            offset=offset,
        )
        return success_json(
            brands=[brand.model_dump(mode="json") for brand in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    return list_brands
