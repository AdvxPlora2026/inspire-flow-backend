from uuid import UUID

from agents import FunctionTool, RunContextWrapper, function_tool

from inspire_flow_backend.core.errors import ProjectNotFoundError
from inspire_flow_backend.schemas.projects import ProjectPublic
from inspire_flow_backend.services import projects as project_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    project_context_error_json,
    project_not_found_error_json,
    success_json,
)


def build_get_project_tool() -> FunctionTool:
    @function_tool(
        name_override="get_project",
        failure_error_function=None,
    )
    async def get_project(
        ctx: RunContextWrapper[AgentRunContext | None],
        project_id: UUID,
    ) -> str:
        """Read one project owned by the authenticated user.

        Args:
            project_id: Project UUID.
        """
        context = ctx.context
        if context is None:
            return project_context_error_json()
        try:
            project = project_service.get_project(
                context.db,
                context.user_id,
                project_id,
            )
        except ProjectNotFoundError:
            return project_not_found_error_json()
        return success_json(project=ProjectPublic.model_validate(project).model_dump(mode="json"))

    return get_project
