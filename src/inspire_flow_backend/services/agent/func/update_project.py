from uuid import UUID

from agents import FunctionTool, RunContextWrapper, function_tool
from pydantic import ValidationError

from inspire_flow_backend.core.errors import ProjectNotFoundError
from inspire_flow_backend.schemas.projects import ProjectPublic, ProjectUpdate
from inspire_flow_backend.services import projects as project_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    invalid_project_error_json,
    project_context_error_json,
    project_not_found_error_json,
    success_json,
)


def build_update_project_tool() -> FunctionTool:
    @function_tool(
        name_override="update_project",
        failure_error_function=None,
    )
    async def update_project(
        ctx: RunContextWrapper[AgentRunContext | None],
        project_id: UUID,
        title: str | None = None,
        type: str | None = None,
        audience: str | None = None,
        summary: str | None = None,
        icon_url: str | None = None,
        clear_icon: bool = False,
    ) -> str:
        """Update selected fields of an owned project.

        Args:
            project_id: Project UUID.
            title: Replacement title.
            type: Replacement category.
            audience: Replacement intended audience.
            summary: Replacement description.
            icon_url: Replacement HTTP or HTTPS project icon URL.
            clear_icon: True to remove the current project icon.
        """
        if clear_icon and icon_url is not None:
            return invalid_project_error_json()
        values = {
            name: value
            for name, value in {
                "title": title,
                "type": type,
                "audience": audience,
                "summary": summary,
            }.items()
            if value is not None
        }
        if clear_icon:
            values["icon_url"] = None
        elif icon_url is not None:
            values["icon_url"] = icon_url
        try:
            payload = ProjectUpdate.model_validate(values)
        except ValidationError:
            return invalid_project_error_json()
        context = ctx.context
        if context is None:
            return project_context_error_json()
        try:
            project = project_service.update_project(
                context.db,
                context.user_id,
                project_id,
                payload,
            )
        except ProjectNotFoundError:
            return project_not_found_error_json()
        return success_json(project=ProjectPublic.model_validate(project).model_dump(mode="json"))

    return update_project
