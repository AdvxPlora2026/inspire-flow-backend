import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.repositories.conversations import get_conversation
from inspire_flow_backend.data.repositories.messages import list_messages_after
from inspire_flow_backend.services.agent.context import AgentContextPolicy
from inspire_flow_backend.services.agent.contracts import TextGenerator
from inspire_flow_backend.services.agent.session_items import (
    SequencedSessionItem,
    group_sequenced_items_by_turn,
    normalize_session_item,
    normalized_item_character_count,
)


@dataclass(frozen=True, slots=True)
class CompactionInput:
    previous_summary: str | None
    items: list[dict[str, object]]
    through_sequence: int


class ContextCompactor(Protocol):
    async def compact(self, value: CompactionInput) -> str: ...


@dataclass(frozen=True, slots=True)
class CompactionOutcome:
    status: str
    through_sequence: int | None = None


class ModelContextCompactor:
    def __init__(self, generator: TextGenerator) -> None:
        self._generator = generator

    async def compact(self, value: CompactionInput) -> str:
        return await self._generator.generate(render_compaction_prompt(value))


async def compact_conversation_if_needed(
    db: Session,
    *,
    user_id: UUID,
    conversation_id: UUID,
    run_id: UUID,
    cipher: ContextCipher,
    policy: AgentContextPolicy,
    compactor: ContextCompactor,
) -> CompactionOutcome:
    conversation = get_conversation(db, user_id, conversation_id)
    if conversation is None or conversation.active_run_id != run_id:
        return CompactionOutcome(status="stale")

    snapshot_cursor = conversation.summary_through_sequence
    messages = list_messages_after(
        db,
        conversation_id,
        sequence=snapshot_cursor,
    )
    sequenced_items = [
        SequencedSessionItem(
            sequence=message.sequence,
            turn_id=message.turn_id,
            item=normalize_session_item(cipher.decrypt_json(message.payload_ciphertext)),
        )
        for message in messages
    ]
    total_characters = sum(normalized_item_character_count(item.item) for item in sequenced_items)
    if total_characters < policy.trigger_characters:
        return CompactionOutcome(status="skipped")

    turns = group_sequenced_items_by_turn(sequenced_items)
    candidate_turns = turns[: -policy.recent_turns] if len(turns) > policy.recent_turns else []
    if not candidate_turns:
        return CompactionOutcome(status="skipped")
    candidates = [item for turn in candidate_turns for item in turn]
    through_sequence = candidates[-1].sequence
    previous_summary = (
        cipher.decrypt_text(conversation.summary_ciphertext)
        if conversation.summary_ciphertext is not None
        else None
    )
    compaction_input = CompactionInput(
        previous_summary=previous_summary,
        items=[item.item for item in candidates],
        through_sequence=through_sequence,
    )
    try:
        summary = (await compactor.compact(compaction_input)).strip()
    except Exception:
        return CompactionOutcome(status="failed")
    if not summary or len(summary) > policy.summary_max_characters:
        return CompactionOutcome(status="failed")

    result = db.execute(
        update(AgentConversation)
        .where(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
            AgentConversation.active_run_id == run_id,
            AgentConversation.summary_through_sequence == snapshot_cursor,
        )
        .values(
            summary_ciphertext=cipher.encrypt_text(summary),
            summary_through_sequence=through_sequence,
            summary_updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        return CompactionOutcome(status="stale")
    db.commit()
    db.refresh(conversation)
    return CompactionOutcome(
        status="compacted",
        through_sequence=through_sequence,
    )


def render_compaction_prompt(value: CompactionInput) -> str:
    payload = {
        "previous_summary": value.previous_summary,
        "items": value.items,
        "through_sequence": value.through_sequence,
    }
    return (
        "请把以下创作对话压缩成简洁中文摘要。保留已确认事实、创作决策、"
        "未解决问题和已有成果状态；明确区分事实与假设。只输出摘要正文。\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
