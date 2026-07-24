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


def build_delete_inspiration_tool() -> FunctionTool:
    @function_tool(
        name_override="delete_inspiration",
        failure_error_function=None,
    )
    async def delete_inspiration(
        ctx: RunContextWrapper[AgentRunContext | None],
        inspiration_id: UUID,
        confirmed: bool = False,
    ) -> str:
        """Preview or delete one owned inspiration.

        Args:
            inspiration_id: Inspiration UUID.
            confirmed: True only after a separate user turn confirms deletion.
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
        if not confirmed:
            return success_json(
                status="confirmation_required",
                inspiration={
                    "id": str(inspiration.id),
                    "title": inspiration.title,
                },
            )
        inspiration_service.delete_inspiration(
            context.db,
            context.user_id,
            inspiration_id,
        )
        return success_json(
            status="deleted",
            inspiration_id=str(inspiration_id),
        )

    return delete_inspiration
