from agents import FunctionTool, RunContextWrapper, function_tool
from pydantic import ValidationError

from inspire_flow_backend.schemas.users import UserProfileTextUpdate
from inspire_flow_backend.services import users as user_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    invalid_user_profile_text_error_json,
    success_json,
    user_context_error_json,
)
from inspire_flow_backend.services.users import ProfileTextContainsCredentialError


def build_update_user_profile_text_tool() -> FunctionTool:
    @function_tool(
        name_override="update_user_profile_text",
        failure_error_function=None,
    )
    async def update_user_profile_text(
        ctx: RunContextWrapper[AgentRunContext | None],
        profile_text: str | None = None,
        clear_profile_text: bool = False,
    ) -> str:
        """Replace the authenticated user's durable profile summary.

        Record only durable facts the user expressed. Never save inferred facts.
        Sensitive information requires an explicit user request to remember it.
        Never save passwords, tokens, API keys, private keys, or recovery codes.

        Args:
            profile_text: Complete replacement profile summary.
            clear_profile_text: True to remove the current profile summary.
        """
        if clear_profile_text and profile_text is not None:
            return invalid_user_profile_text_error_json()
        values: dict[str, object] = {}
        if clear_profile_text:
            values["profile_text"] = None
        elif profile_text is not None:
            values["profile_text"] = profile_text
        try:
            payload = UserProfileTextUpdate.model_validate(values)
        except ValidationError:
            return invalid_user_profile_text_error_json()
        context = ctx.context
        if context is None:
            return user_context_error_json()
        try:
            user = user_service.update_user_profile_text(
                context.db,
                context.user_id,
                payload,
            )
        except ProfileTextContainsCredentialError:
            return invalid_user_profile_text_error_json()
        if user is None:
            return user_context_error_json()
        return success_json(profile_text=user.profile_text)

    return update_user_profile_text
