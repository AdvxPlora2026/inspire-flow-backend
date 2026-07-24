from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agents import FunctionTool, function_tool

from inspire_flow_backend.services.agent.contracts import (
    AgentToolError,
    Clock,
    DateTimeResult,
)
from inspire_flow_backend.services.agent.func._shared import error_json


def get_current_datetime(
    timezone_name: str,
    clock: Clock,
) -> DateTimeResult:
    try:
        timezone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise AgentToolError(
            "invalid_timezone",
            "Unknown IANA timezone",
        ) from error

    current = clock()
    if current.tzinfo is None or current.utcoffset() is None:
        raise RuntimeError("Agent clock must return a timezone-aware datetime")
    localized = current.astimezone(timezone)
    return DateTimeResult(
        timezone=timezone.key,
        iso_datetime=localized.isoformat(),
        unix_timestamp=int(current.timestamp()),
    )


def build_current_datetime_tool(*, clock: Clock) -> FunctionTool:
    @function_tool(
        name_override="current_datetime",
        failure_error_function=None,
    )
    def current_datetime(timezone_name: str = "UTC") -> str:
        """Return the current date and time in an IANA timezone.

        Args:
            timezone_name: IANA timezone such as UTC or Asia/Shanghai.
        """
        try:
            return get_current_datetime(timezone_name, clock).model_dump_json()
        except AgentToolError as error:
            return error_json(error)

    return current_datetime
