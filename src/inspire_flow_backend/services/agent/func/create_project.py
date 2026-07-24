from uuid import UUID

from agents import FunctionTool, RunContextWrapper, function_tool
from pydantic import ValidationError

from inspire_flow_backend.core.errors import InspirationNotFoundError
from inspire_flow_backend.schemas.projects import ProjectCreate, ProjectDraft, ProjectPublic
from inspire_flow_backend.services import inspirations as inspiration_service
from inspire_flow_backend.services import projects as project_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    get_project_context,
    inspiration_not_found_error_json,
    invalid_project_error_json,
    project_context_error_json,
    success_json,
)


def build_create_project_tool() -> FunctionTool:
    @function_tool(
        name_override="create_project",
        failure_error_function=None,
    )
    async def create_project(
        ctx: RunContextWrapper[AgentRunContext | None],
        title: str,
        type: str,
        audience: str,
        summary: str,
        icon_url: str | None = None,
        inspiration_ids: list[UUID] | None = None,
        confirmed: bool = False,
    ) -> str:
        """Prepare or save a project owned by the authenticated user.

        Args:
            title: Concise project title.
            type: Bilibili-like category or a normalized custom type.
            audience: Intended audience.
            summary: Short project description.
            icon_url: Optional HTTP or HTTPS project icon URL.
            inspiration_ids: Existing owned inspirations to link after creation.
            confirmed: True only after the user explicitly confirms saving.
        """
        try:
            payload = ProjectCreate(
                title=title,
                type=type,
                audience=audience,
                summary=summary,
                icon_url=icon_url,
            )
        except ValidationError:
            return invalid_project_error_json()
        context = get_project_context(ctx)
        if context is None:
            return project_context_error_json()
        if inspiration_ids is not None and (
            len(inspiration_ids) > 100 or len(set(inspiration_ids)) != len(inspiration_ids)
        ):
            return invalid_project_error_json()
        try:
            inspirations = inspiration_service.get_owned_inspirations(
                context.db,
                context.user_id,
                inspiration_ids or [],
            )
        except InspirationNotFoundError:
            return inspiration_not_found_error_json()
        inspiration_summaries = [
            {"id": str(inspiration.id), "title": inspiration.title} for inspiration in inspirations
        ]
        if not confirmed:
            draft = ProjectDraft.model_validate(payload.model_dump())
            result: dict[str, object] = {
                "status": "confirmation_required",
                "draft": draft.model_dump(mode="json"),
            }
            if inspiration_summaries:
                result["inspirations"] = inspiration_summaries
            return success_json(
                **result,
            )
        project = project_service.create_project(
            context.db,
            context.user_id,
            payload,
            inspiration_ids=inspiration_ids,
        )
        return success_json(
            status="created",
            project=ProjectPublic.model_validate(project).model_dump(mode="json"),
        )

    return create_project
