from uuid import UUID

from agents import FunctionTool, RunContextWrapper, function_tool
from pydantic import ValidationError

from inspire_flow_backend.core.errors import (
    InspirationAssociationRequiredError,
    InspirationNotFoundError,
    ProjectNotFoundError,
)
from inspire_flow_backend.schemas.inspirations import (
    InspirationStatus,
    InspirationUpdate,
)
from inspire_flow_backend.services import inspirations as inspiration_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    inspiration_context_error_json,
    inspiration_not_found_error_json,
    invalid_inspiration_error_json,
    project_not_found_error_json,
    success_json,
)


def build_update_inspiration_tool() -> FunctionTool:
    @function_tool(
        name_override="update_inspiration",
        failure_error_function=None,
    )
    async def update_inspiration(
        ctx: RunContextWrapper[AgentRunContext | None],
        inspiration_id: UUID,
        title: str | None = None,
        content: str | None = None,
        status: InspirationStatus | None = None,
        project_ids: list[UUID] | None = None,
        clear_title: bool = False,
    ) -> str:
        """Update selected fields or replace project links for an inspiration.

        Args:
            inspiration_id: Inspiration UUID.
            title: Replacement title.
            content: Replacement idea content.
            status: Replacement workflow status.
            project_ids: Complete replacement project UUID list.
            clear_title: True to remove the current title.
        """
        if clear_title and title is not None:
            return invalid_inspiration_error_json()
        values: dict[str, object] = {}
        if clear_title:
            values["title"] = None
        elif title is not None:
            values["title"] = title
        if content is not None:
            values["content"] = content
        if status is not None:
            values["status"] = status
        if project_ids is not None:
            values["project_ids"] = project_ids
        try:
            payload = InspirationUpdate.model_validate(values)
        except ValidationError:
            return invalid_inspiration_error_json()
        context = ctx.context
        if context is None:
            return inspiration_context_error_json()
        try:
            inspiration = inspiration_service.update_inspiration(
                context.db,
                context.user_id,
                inspiration_id,
                payload,
            )
        except InspirationNotFoundError:
            return inspiration_not_found_error_json()
        except ProjectNotFoundError:
            return project_not_found_error_json()
        except InspirationAssociationRequiredError:
            return invalid_inspiration_error_json()
        return success_json(
            inspiration=inspiration_service.to_public_inspiration(inspiration).model_dump(
                mode="json"
            )
        )

    return update_inspiration
