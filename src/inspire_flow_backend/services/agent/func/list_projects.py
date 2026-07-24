from agents import FunctionTool, RunContextWrapper, function_tool

from inspire_flow_backend.services import projects as project_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    invalid_project_error_json,
    project_context_error_json,
    success_json,
)


def build_list_projects_tool() -> FunctionTool:
    @function_tool(
        name_override="list_projects",
        failure_error_function=None,
    )
    async def list_projects(
        ctx: RunContextWrapper[AgentRunContext | None],
        limit: int = 50,
        offset: int = 0,
    ) -> str:
        """List projects owned by the authenticated user.

        Args:
            limit: Page size from 1 to 100.
            offset: Number of projects to skip.
        """
        context = ctx.context
        if context is None:
            return project_context_error_json()
        if (
            isinstance(limit, bool)
            or not 1 <= limit <= 100
            or isinstance(offset, bool)
            or offset < 0
        ):
            return invalid_project_error_json()
        page = project_service.list_projects(
            context.db,
            context.user_id,
            limit=limit,
            offset=offset,
        )
        return success_json(
            projects=[project.model_dump(mode="json") for project in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    return list_projects
