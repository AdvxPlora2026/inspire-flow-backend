from uuid import UUID

from agents import FunctionTool, RunContextWrapper, function_tool

from inspire_flow_backend.core.errors import InspirationNotFoundError
from inspire_flow_backend.services import inspirations as inspiration_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    inspiration_context_error_json,
    inspiration_not_found_error_json,
    success_json,
)


def build_get_inspiration_tool() -> FunctionTool:
    @function_tool(
        name_override="get_inspiration",
        failure_error_function=None,
    )
    async def get_inspiration(
        ctx: RunContextWrapper[AgentRunContext | None],
        inspiration_id: UUID,
    ) -> str:
        """Read one inspiration owned by the authenticated user.

        Args:
            inspiration_id: Inspiration UUID.
        """
        context = ctx.context
        if context is None:
            return inspiration_context_error_json()
        try:
            inspiration = inspiration_service.get_inspiration(
                context.db,
                context.user_id,
                inspiration_id,
            )
        except InspirationNotFoundError:
            return inspiration_not_found_error_json()
        return success_json(
            inspiration=inspiration_service.to_public_inspiration(inspiration).model_dump(
                mode="json"
            )
        )

    return get_inspiration
