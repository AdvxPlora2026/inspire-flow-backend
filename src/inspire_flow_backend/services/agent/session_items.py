import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, cast
from uuid import UUID

from agents import TResponseInputItem
from pydantic import BaseModel

from inspire_flow_backend.core.context_security import redact_json_credentials


def normalize_session_item(item: object) -> dict[str, Any]:
    value: object
    if isinstance(item, BaseModel):
        value = item.model_dump(mode="json", exclude_none=True)
    elif is_dataclass(item) and not isinstance(item, type):
        value = asdict(item)
    elif isinstance(item, Mapping):
        value = dict(item)
    else:
        raise TypeError("Agent session items must be mapping-like")

    redacted = redact_json_credentials(value)
    if not isinstance(redacted, dict) or not all(isinstance(key, str) for key in redacted):
        raise TypeError("Agent session items must have string keys")
    try:
        serialized = json.dumps(redacted, ensure_ascii=False)
        normalized = json.loads(serialized)
    except (TypeError, ValueError) as exc:
        raise TypeError("Agent session items must be JSON serializable") from exc
    if not isinstance(normalized, dict):
        raise TypeError("Agent session items must be JSON objects")
    return normalized


def restore_session_item(value: object) -> TResponseInputItem:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("Persisted Agent session item is invalid")
    return cast(TResponseInputItem, value)


def item_type_and_role(item: Mapping[str, object]) -> tuple[str, str | None]:
    item_type = item.get("type")
    role = item.get("role")
    return (
        item_type if isinstance(item_type, str) else "message",
        role if isinstance(role, str) else None,
    )


def public_message_text(item: Mapping[str, object]) -> tuple[str, str] | None:
    role = item.get("role")
    if role not in {"user", "assistant"}:
        return None
    content = item.get("content")
    if isinstance(content, str):
        return role, content
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, Mapping):
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    if not parts:
        return None
    return role, "\n".join(parts)


def normalized_item_character_count(item: Mapping[str, object]) -> int:
    return len(json.dumps(item, ensure_ascii=False, separators=(",", ":")))


def truncate_tool_output(
    item: Mapping[str, object],
    *,
    max_characters: int,
) -> dict[str, Any]:
    normalized = normalize_session_item(item)
    if normalized.get("type") != "function_call_output":
        return normalized
    output = normalized.get("output")
    if not isinstance(output, str) or len(output) <= max_characters:
        return normalized
    normalized["output"] = f"{output[:max_characters]}\n[TRUNCATED]"
    return normalized


@dataclass(frozen=True, slots=True)
class SequencedSessionItem:
    sequence: int
    turn_id: UUID
    item: dict[str, Any]


def group_complete_turns(
    items: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    turns: list[list[dict[str, Any]]] = []
    for item in items:
        if item.get("role") == "user" or not turns:
            turns.append([])
        turns[-1].append(item)
    return turns


def group_sequenced_items_by_turn(
    items: list[SequencedSessionItem],
) -> list[list[SequencedSessionItem]]:
    turns: list[list[SequencedSessionItem]] = []
    previous_turn_id: UUID | None = None
    for item in items:
        if item.turn_id != previous_turn_id:
            turns.append([])
            previous_turn_id = item.turn_id
        turns[-1].append(item)
    return turns


def truncate_item_for_model(
    item: Mapping[str, object],
    *,
    max_characters: int,
) -> dict[str, Any]:
    normalized = normalize_session_item(item)
    if normalized_item_character_count(normalized) <= max_characters:
        return normalized

    if normalized.get("type") == "function_call_output":
        return truncate_tool_output(
            normalized,
            max_characters=max(16, max_characters // 2),
        )

    content = normalized.get("content")
    text_budget = max(16, max_characters // 2)
    if isinstance(content, str) and len(content) > text_budget:
        normalized["content"] = f"{content[:text_budget]}\n[TRUNCATED]"
    elif isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and len(text) > text_budget:
                part["text"] = f"{text[:text_budget]}\n[TRUNCATED]"
    return normalized
