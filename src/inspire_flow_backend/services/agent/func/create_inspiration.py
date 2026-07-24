from uuid import UUID

from agents import FunctionTool, RunContextWrapper, function_tool
from pydantic import ValidationError

from inspire_flow_backend.core.errors import (
    ConversationNotFoundError,
    InspirationAssociationRequiredError,
    ProjectNotFoundError,
)
from inspire_flow_backend.schemas.inspirations import (
    InspirationCreate,
    InspirationSourceType,
    InspirationStatus,
)
from inspire_flow_backend.services import inspirations as inspiration_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    inspiration_context_error_json,
    invalid_inspiration_error_json,
    project_not_found_error_json,
    success_json,
)


def build_create_inspiration_tool() -> FunctionTool:
    @function_tool(
        name_override="create_inspiration",
        failure_error_function=None,
    )
    async def create_inspiration(
        ctx: RunContextWrapper[AgentRunContext | None],
        content: str,
        title: str | None = None,
        project_ids: list[UUID] | None = None,
        status: InspirationStatus = InspirationStatus.inbox,
    ) -> str:
        """Save a clear creative idea for the authenticated user.

        Args:
            content: The user's concise or developed creative idea.
            title: Optional short title generated only when it is useful.
            project_ids: Existing owned projects to associate.
            status: Current inspiration workflow state.
        """
        context = ctx.context
        if context is None:
            return inspiration_context_error_json()
        try:
            payload = InspirationCreate(
                title=title,
                content=content,
                status=status,
                project_ids=project_ids or [],
            )
            inspiration = inspiration_service.create_inspiration(
                context.db,
                context.user_id,
                payload,
                source_type=InspirationSourceType.agent,
                source_conversation_id=context.conversation_id,
                source_message_id=context.source_message_id,
            )
        except ValidationError:
            return invalid_inspiration_error_json()
        except InspirationAssociationRequiredError:
            return invalid_inspiration_error_json()
        except ConversationNotFoundError:
            return invalid_inspiration_error_json()
        except ProjectNotFoundError:
            return project_not_found_error_json()
        return success_json(
            status="created",
            inspiration=inspiration_service.to_public_inspiration(inspiration).model_dump(
                mode="json"
            ),
        )

    return create_inspiration
