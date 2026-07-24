from uuid import UUID

from agents import FunctionTool, RunContextWrapper, function_tool

from inspire_flow_backend.core.errors import ProjectNotFoundError
from inspire_flow_backend.services import projects as project_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    project_context_error_json,
    project_not_found_error_json,
    success_json,
)


def build_delete_project_tool() -> FunctionTool:
    @function_tool(
        name_override="delete_project",
        failure_error_function=None,
    )
    async def delete_project(
        ctx: RunContextWrapper[AgentRunContext | None],
        project_id: UUID,
        confirmed: bool = False,
    ) -> str:
        """Preview or delete an owned project.

        Args:
            project_id: Project UUID.
            confirmed: True only after a separate user turn confirms deletion.
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
        if not confirmed:
            return success_json(
                status="confirmation_required",
                project={"id": str(project.id), "title": project.title},
            )
        project_service.delete_project(context.db, context.user_id, project_id)
        return success_json(status="deleted", project_id=str(project_id))

    return delete_project
