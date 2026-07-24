from collections.abc import Callable
from typing import Any

from agents import RunContextWrapper

from inspire_flow_backend.services.agent.contracts import (
    AgentToolError,
    ToolErrorBody,
    ToolErrorResult,
)


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
