from uuid import UUID

from agents import FunctionTool, RunContextWrapper, function_tool

from inspire_flow_backend.core.errors import (
    OrphanedInspirationsConfirmationRequiredError,
    ProjectNotFoundError,
)
from inspire_flow_backend.services import inspirations as inspiration_service
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
        delete_orphan_inspirations: bool = False,
    ) -> str:
        """Preview or delete an owned project.

        Args:
            project_id: Project UUID.
            confirmed: True only after a separate user turn confirms deletion.
            delete_orphan_inspirations: True only after the shown cascade is confirmed.
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
        orphan_candidates = inspiration_service.project_orphan_candidates(
            context.db,
            context.user_id,
            project_id,
        )
        if not confirmed or (orphan_candidates and not delete_orphan_inspirations):
            result: dict[str, object] = {
                "status": "confirmation_required",
                "project": {
                    "id": str(project.id),
                    "title": project.title,
                },
            }
            if orphan_candidates:
                result["orphaned_inspirations"] = inspiration_service.orphan_impact_details(
                    orphan_candidates
                )
            return success_json(**result)
        try:
            project_service.delete_project(
                context.db,
                context.user_id,
                project_id,
                delete_orphan_inspirations=delete_orphan_inspirations,
            )
        except OrphanedInspirationsConfirmationRequiredError:
            return success_json(
                status="confirmation_required",
                project={"id": str(project.id), "title": project.title},
                orphaned_inspirations=(
                    inspiration_service.orphan_impact_details(
                        inspiration_service.project_orphan_candidates(
                            context.db,
                            context.user_id,
                            project_id,
                        )
                    )
                ),
            )
        return success_json(status="deleted", project_id=str(project_id))

    return delete_project
