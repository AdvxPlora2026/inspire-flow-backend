from uuid import UUID

from agents import FunctionTool, RunContextWrapper, function_tool

from inspire_flow_backend.core.errors import (
    InspirationNotFoundError,
    ProjectNotFoundError,
)
from inspire_flow_backend.services import inspirations as inspiration_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    inspiration_context_error_json,
    inspiration_not_found_error_json,
    project_not_found_error_json,
    success_json,
)


def build_add_inspiration_project_tool() -> FunctionTool:
    @function_tool(
        name_override="add_inspiration_project",
        failure_error_function=None,
    )
    async def add_inspiration_project(
        ctx: RunContextWrapper[AgentRunContext | None],
        inspiration_id: UUID,
        project_id: UUID,
    ) -> str:
        """Add one owned project link to an owned inspiration.

        Args:
            inspiration_id: Inspiration UUID.
            project_id: Project UUID.
        """
        context = ctx.context
        if context is None:
            return inspiration_context_error_json()
        try:
            inspiration_service.add_project_link(
                context.db,
                context.user_id,
                inspiration_id,
                project_id,
            )
        except InspirationNotFoundError:
            return inspiration_not_found_error_json()
        except ProjectNotFoundError:
            return project_not_found_error_json()
        return success_json(
            status="added",
            inspiration_id=str(inspiration_id),
            project_id=str(project_id),
        )

    return add_inspiration_project
