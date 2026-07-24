from agents import FunctionTool, RunContextWrapper, function_tool
from pydantic import ValidationError

from inspire_flow_backend.core.errors import NicknameConflictError
from inspire_flow_backend.schemas.users import UserPublic, UserUpdate
from inspire_flow_backend.services import users as user_service
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.func._shared import (
    invalid_user_error_json,
    nickname_conflict_error_json,
    success_json,
    user_context_error_json,
)


def build_update_current_user_tool() -> FunctionTool:
    @function_tool(
        name_override="update_current_user",
        failure_error_function=None,
    )
    async def update_current_user(
        ctx: RunContextWrapper[AgentRunContext | None],
        nickname: str | None = None,
        avatar_url: str | None = None,
        clear_avatar: bool = False,
    ) -> str:
        """Update the authenticated user's visible identity after an explicit request.

        Args:
            nickname: Replacement nickname explicitly requested by the user.
            avatar_url: Replacement HTTP or HTTPS avatar URL.
            clear_avatar: True to remove the current avatar.
        """
        if clear_avatar and avatar_url is not None:
            return invalid_user_error_json()
        values: dict[str, object] = {}
        if nickname is not None:
            values["nickname"] = nickname
        if clear_avatar:
            values["avatar_url"] = None
        elif avatar_url is not None:
            values["avatar_url"] = avatar_url
        try:
            payload = UserUpdate.model_validate(values)
        except ValidationError:
            return invalid_user_error_json()
        context = ctx.context
        if context is None:
            return user_context_error_json()
        try:
            user = user_service.update_user_by_id(
                context.db,
                context.user_id,
                payload,
            )
        except NicknameConflictError:
            return nickname_conflict_error_json()
        if user is None:
            return user_context_error_json()
        return success_json(
            user=UserPublic.model_validate(user).model_dump(mode="json"),
        )

    return update_current_user
