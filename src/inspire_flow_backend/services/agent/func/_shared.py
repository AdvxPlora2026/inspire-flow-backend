import json
from collections.abc import Callable
from typing import Any

from agents import RunContextWrapper

from inspire_flow_backend.services.agent.contracts import (
    AgentRunContext,
    AgentToolError,
    ToolErrorBody,
    ToolErrorResult,
)


def success_json(**payload: object) -> str:
    return json.dumps(
        {"ok": True, **payload},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def get_project_context(
    ctx: RunContextWrapper[AgentRunContext | None],
) -> AgentRunContext | None:
    return ctx.context


def project_context_error_json() -> str:
    return error_json(
        AgentToolError(
            "project_context_unavailable",
            "Authenticated project context is unavailable",
        )
    )


def project_not_found_error_json() -> str:
    return error_json(AgentToolError("project_not_found", "Project not found"))


def invalid_project_error_json() -> str:
    return error_json(AgentToolError("invalid_project", "Project fields are invalid"))


def error_json(error: AgentToolError) -> str:
    return ToolErrorResult(
        error=ToolErrorBody(
            code=error.code,
            message=error.message,
        )
    ).model_dump_json()


def timeout_error_formatter(
    code: str,
    message: str,
) -> Callable[[RunContextWrapper[Any], Exception], str]:
    def format_timeout(
        context: RunContextWrapper[Any],
        error: Exception,
    ) -> str:
        del context, error
        return error_json(AgentToolError(code, message))

    return format_timeout
