from uuid import UUID

from agents import FunctionTool, RunContextWrapper, function_tool

from inspire_flow_backend.core.errors import ProjectNotFoundError
from inspire_flow_backend.schemas.inspirations import (
    InspirationSortBy,
    InspirationSourceType,
    InspirationStatus,
    SortOrder,
)
from inspire_flow_backend.services import inspirations as inspiration_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    inspiration_context_error_json,
    invalid_inspiration_error_json,
    project_not_found_error_json,
    success_json,
)


def build_list_inspirations_tool() -> FunctionTool:
    @function_tool(
        name_override="list_inspirations",
        failure_error_function=None,
    )
    async def list_inspirations(
        ctx: RunContextWrapper[AgentRunContext | None],
        project_id: UUID | None = None,
        status: InspirationStatus | None = None,
        source_type: InspirationSourceType | None = None,
        query: str | None = None,
        sort_by: InspirationSortBy = InspirationSortBy.updated_at,
        sort_order: SortOrder = SortOrder.desc,
        limit: int = 50,
        offset: int = 0,
    ) -> str:
        """List and search inspirations owned by the authenticated user.

        Args:
            project_id: Optional owned project filter.
            status: Optional workflow status filter.
            source_type: Optional capture source filter.
            query: Optional title or content keyword.
            sort_by: Timestamp field used for ordering.
            sort_order: Ascending or descending order.
            limit: Page size from 1 to 100.
            offset: Number of matching inspirations to skip.
        """
        context = ctx.context
        if context is None:
            return inspiration_context_error_json()
        if (
            isinstance(limit, bool)
            or not 1 <= limit <= 100
            or isinstance(offset, bool)
            or offset < 0
            or (query is not None and len(query) > 300)
        ):
            return invalid_inspiration_error_json()
        try:
            page = inspiration_service.list_inspirations(
                context.db,
                context.user_id,
                project_id=project_id,
                status=status,
                source_type=source_type,
                query=query,
                sort_by=sort_by,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        except ProjectNotFoundError:
            return project_not_found_error_json()
        return success_json(
            inspirations=[inspiration.model_dump(mode="json") for inspiration in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    return list_inspirations
