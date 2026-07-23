from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Literal

from pydantic import BaseModel

type Clock = Callable[[], datetime]
type HostResolver = Callable[[str], Awaitable[set[str]]]


class AgentToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ToolErrorBody(BaseModel):
    code: str
    message: str


class ToolErrorResult(BaseModel):
    ok: Literal[False] = False
    error: ToolErrorBody


class DateTimeResult(BaseModel):
    ok: Literal[True] = True
    timezone: str
    iso_datetime: str
    unix_timestamp: int


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class SearchResponse(BaseModel):
    ok: Literal[True] = True
    query: str
    provider: str
    results: list[SearchResult]


class FetchResponse(BaseModel):
    ok: Literal[True] = True
    url: str
    content_type: str
    title: str | None = None
    text: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class AgentToolSettings:
    request_timeout_seconds: float = 10.0
    tool_timeout_seconds: float = 15.0
    default_search_results: int = 5
    max_search_results: int = 10
    max_query_characters: int = 300
    max_search_response_bytes: int = 512 * 1024
    max_fetch_response_bytes: int = 1024 * 1024
    max_fetch_output_characters: int = 20_000
    max_redirects: int = 3
    user_agent: str = "InspireFlowBackend/0.1"

    def __post_init__(self) -> None:
        positive_timeouts = {
            "request_timeout_seconds": self.request_timeout_seconds,
            "tool_timeout_seconds": self.tool_timeout_seconds,
        }
        for name, value in positive_timeouts.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive finite number")

        positive_integers = {
            "default_search_results": self.default_search_results,
            "max_search_results": self.max_search_results,
            "max_query_characters": self.max_query_characters,
            "max_search_response_bytes": self.max_search_response_bytes,
            "max_fetch_response_bytes": self.max_fetch_response_bytes,
            "max_fetch_output_characters": self.max_fetch_output_characters,
        }
        for name, value in positive_integers.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.default_search_results > self.max_search_results:
            raise ValueError("default_search_results must not exceed max_search_results")
        if (
            isinstance(self.max_redirects, bool)
            or not isinstance(self.max_redirects, int)
            or self.max_redirects < 0
        ):
            raise ValueError("max_redirects must be a non-negative integer")
        if not isinstance(self.user_agent, str) or not self.user_agent.strip():
            raise ValueError("user_agent must not be blank")
