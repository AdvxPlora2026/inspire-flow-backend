from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import httpx
import openai
from agents import AgentsException, RunConfig
from sqlalchemy.orm import Session

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.core.context_security import (
    ContextCipher,
    redact_credentials,
)
from inspire_flow_backend.core.errors import AgentRunFailedError
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.data.repositories.messages import list_turn_messages
from inspire_flow_backend.schemas.conversations import AgentTurnPublic
from inspire_flow_backend.schemas.memories import UserMemoryPublic
from inspire_flow_backend.services.agent.compaction import (
    compact_conversation_if_needed,
)
from inspire_flow_backend.services.agent.context import (
    AgentContextPolicy,
    ContextInputFilter,
    build_dynamic_context,
)
from inspire_flow_backend.services.agent.contracts import AgentRunContext
from inspire_flow_backend.services.agent.runtime import AgentRuntime
from inspire_flow_backend.services.agent.session import DatabaseAgentSession
from inspire_flow_backend.services.agent.session_items import public_message_text
from inspire_flow_backend.services.conversations import (
    claim_conversation_run,
    release_conversation_run,
)
from inspire_flow_backend.services.memories import store_memory, to_public_memory


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    id: UUID
    turn_id: UUID
    sequence: int
    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentTurn:
    turn_id: UUID
    user_message: ConversationMessage
    assistant_message: ConversationMessage
    memory_updates: tuple[UserMemoryPublic, ...]
    memory_extraction_status: str


@dataclass(frozen=True, slots=True)
class AgentStreamEvent:
    event: str
    data: dict[str, object]


async def run_conversation_turn(
    db: Session,
    *,
    user: User,
    conversation_id: UUID,
    content: str,
    runtime: AgentRuntime,
    cipher: ContextCipher,
    settings: Settings,
) -> AgentTurn:
    run_id = uuid4()
    turn_id = uuid4()
    policy = AgentContextPolicy.from_settings(settings)
    conversation = claim_conversation_run(
        db,
        user_id=user.id,
        conversation_id=conversation_id,
        run_id=run_id,
        stale_before=utc_now() - timedelta(seconds=settings.agent_run_lock_ttl_seconds),
    )
    try:
        await compact_conversation_if_needed(
            db,
            user_id=user.id,
            conversation_id=conversation_id,
            run_id=run_id,
            cipher=cipher,
            policy=policy,
            compactor=runtime.compactor,
        )
        redacted_content = redact_credentials(content).value.strip()
        if not redacted_content:
            raise ValueError("conversation message cannot be blank")
        session = DatabaseAgentSession(
            db=db,
            user_id=user.id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            run_id=run_id,
            cipher=cipher,
        )
        await session.add_items([{"role": "user", "content": redacted_content}])
        persisted_user_message = next(
            (
                message
                for message in list_turn_messages(
                    db,
                    conversation_id,
                    turn_id,
                )
                if message.role == "user"
            ),
            None,
        )
        if persisted_user_message is None:
            raise AgentRunFailedError
        if conversation.title is None:
            conversation.title = redacted_content[:120]
            conversation.updated_at = utc_now()
            db.commit()

        dynamic_context = build_dynamic_context(
            db,
            user=user,
            conversation=conversation,
            cipher=cipher,
            policy=policy,
        )
        run_config = RunConfig(
            trace_include_sensitive_data=False,
            group_id=str(conversation_id),
            call_model_input_filter=ContextInputFilter(
                dynamic_context,
                policy=policy,
            ),
        )
        try:
            await runtime.conversation_agent.run(
                [],
                context=AgentRunContext(
                    db=db,
                    user_id=user.id,
                    conversation_id=conversation_id,
                    source_message_id=persisted_user_message.id,
                ),
                session=session,
                run_config=run_config,
            )
        except (AgentsException, openai.APIError, httpx.HTTPError) as exc:
            db.rollback()
            raise AgentRunFailedError from exc

        public_messages = _public_turn_messages(
            list_turn_messages(db, conversation_id, turn_id),
            cipher,
        )
        user_message = next(
            (message for message in public_messages if message.role == "user"),
            None,
        )
        assistant_message = next(
            (message for message in reversed(public_messages) if message.role == "assistant"),
            None,
        )
        if user_message is None or assistant_message is None:
            raise AgentRunFailedError

        try:
            extraction = await runtime.memory_extractor.extract(redacted_content)
        except Exception:
            extraction = None
        memory_updates: list[UserMemoryPublic] = []
        if extraction is not None and extraction.status == "completed":
            for candidate in extraction.candidates:
                try:
                    memory = store_memory(
                        db,
                        user_id=user.id,
                        category=candidate.category,
                        content=candidate.content,
                        origin=candidate.origin,
                        is_sensitive=candidate.is_sensitive,
                        cipher=cipher,
                        source_conversation_id=conversation_id,
                        source_message_id=user_message.id,
                    )
                except Exception:
                    continue
                memory_updates.append(to_public_memory(memory, cipher))
        extraction_status = extraction.status if extraction is not None else "failed"
        return AgentTurn(
            turn_id=turn_id,
            user_message=user_message,
            assistant_message=assistant_message,
            memory_updates=tuple(memory_updates),
            memory_extraction_status=extraction_status,
        )
    finally:
        release_conversation_run(
            db,
            user_id=user.id,
            conversation_id=conversation_id,
            run_id=run_id,
        )


async def stream_conversation_turn(
    db: Session,
    *,
    user: User,
    conversation_id: UUID,
    content: str,
    runtime: AgentRuntime,
    cipher: ContextCipher,
    settings: Settings,
    run_id: UUID,
    turn_id: UUID,
) -> AsyncIterator[AgentStreamEvent]:
    policy = AgentContextPolicy.from_settings(settings)
    conversation = claim_conversation_run(
        db,
        user_id=user.id,
        conversation_id=conversation_id,
        run_id=run_id,
        stale_before=utc_now() - timedelta(seconds=settings.agent_run_lock_ttl_seconds),
    )
    try:
        yield AgentStreamEvent(
            event="turn.started",
            data={"turn_id": str(turn_id)},
        )
        await compact_conversation_if_needed(
            db,
            user_id=user.id,
            conversation_id=conversation_id,
            run_id=run_id,
            cipher=cipher,
            policy=policy,
            compactor=runtime.compactor,
        )
        redacted_content = redact_credentials(content).value.strip()
        if not redacted_content:
            raise ValueError("conversation message cannot be blank")
        session = DatabaseAgentSession(
            db=db,
            user_id=user.id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            run_id=run_id,
            cipher=cipher,
        )
        await session.add_items([{"role": "user", "content": redacted_content}])
        persisted_user_message = next(
            (
                message
                for message in list_turn_messages(db, conversation_id, turn_id)
                if message.role == "user"
            ),
            None,
        )
        if persisted_user_message is None:
            raise AgentRunFailedError
        if conversation.title is None:
            conversation.title = redacted_content[:120]
            conversation.updated_at = utc_now()
            db.commit()

        dynamic_context = build_dynamic_context(
            db,
            user=user,
            conversation=conversation,
            cipher=cipher,
            policy=policy,
        )
        run_config = RunConfig(
            trace_include_sensitive_data=False,
            group_id=str(conversation_id),
            call_model_input_filter=ContextInputFilter(
                dynamic_context,
                policy=policy,
            ),
        )
        try:
            streamed = runtime.conversation_agent.run_streamed(
                [],
                context=AgentRunContext(
                    db=db,
                    user_id=user.id,
                    conversation_id=conversation_id,
                    source_message_id=persisted_user_message.id,
                ),
                session=session,
                run_config=run_config,
            )
            tool_names: dict[str, str] = {}
            async for event in streamed.stream_events():
                event_type = getattr(event, "type", "")
                if event_type == "raw_response_event":
                    raw = getattr(event, "data", None)
                    if getattr(raw, "type", "") == "response.output_text.delta":
                        delta = getattr(raw, "delta", None)
                        if isinstance(delta, str) and delta:
                            yield AgentStreamEvent(
                                event="response.delta",
                                data={"turn_id": str(turn_id), "delta": delta},
                            )
                elif event_type == "run_item_stream_event":
                    item_name = getattr(event, "name", "")
                    item = getattr(event, "item", None)
                    raw_item = getattr(item, "raw_item", None)
                    call_id = str(
                        getattr(raw_item, "call_id", None) or getattr(raw_item, "id", None) or ""
                    )
                    if item_name == "tool_called":
                        tool_name = _safe_tool_name(
                            getattr(raw_item, "name", None) or getattr(item, "name", None)
                        )
                        if call_id:
                            tool_names[call_id] = tool_name
                        yield AgentStreamEvent(
                            event="tool.started",
                            data={"turn_id": str(turn_id), "tool": tool_name},
                        )
                    elif item_name == "tool_output":
                        yield AgentStreamEvent(
                            event="tool.completed",
                            data={
                                "turn_id": str(turn_id),
                                "tool": tool_names.get(call_id, "tool"),
                                "status": "completed",
                            },
                        )
        except (AgentsException, openai.APIError, httpx.HTTPError) as exc:
            db.rollback()
            raise AgentRunFailedError from exc

        public_messages = _public_turn_messages(
            list_turn_messages(db, conversation_id, turn_id),
            cipher,
        )
        user_message = next(
            (message for message in public_messages if message.role == "user"),
            None,
        )
        assistant_message = next(
            (message for message in reversed(public_messages) if message.role == "assistant"),
            None,
        )
        if user_message is None or assistant_message is None:
            raise AgentRunFailedError

        try:
            extraction = await runtime.memory_extractor.extract(redacted_content)
        except Exception:
            extraction = None
        memory_updates: list[UserMemoryPublic] = []
        if extraction is not None and extraction.status == "completed":
            for candidate in extraction.candidates:
                try:
                    memory = store_memory(
                        db,
                        user_id=user.id,
                        category=candidate.category,
                        content=candidate.content,
                        origin=candidate.origin,
                        is_sensitive=candidate.is_sensitive,
                        cipher=cipher,
                        source_conversation_id=conversation_id,
                        source_message_id=user_message.id,
                    )
                except Exception:
                    continue
                memory_updates.append(to_public_memory(memory, cipher))
        turn = AgentTurn(
            turn_id=turn_id,
            user_message=user_message,
            assistant_message=assistant_message,
            memory_updates=tuple(memory_updates),
            memory_extraction_status=(extraction.status if extraction is not None else "failed"),
        )
        yield AgentStreamEvent(
            event="turn.completed",
            data=AgentTurnPublic.model_validate(turn).model_dump(mode="json"),
        )
    finally:
        release_conversation_run(
            db,
            user_id=user.id,
            conversation_id=conversation_id,
            run_id=run_id,
        )


def _safe_tool_name(value: object) -> str:
    if not isinstance(value, str):
        return "tool"
    normalized = "".join(
        character for character in value[:64] if character.isalnum() or character in {"_", "-", "."}
    )
    return normalized or "tool"


def _public_turn_messages(
    messages: list[AgentMessage],
    cipher: ContextCipher,
) -> list[ConversationMessage]:
    projected: list[ConversationMessage] = []
    for message in messages:
        payload = cipher.decrypt_json(message.payload_ciphertext)
        if not isinstance(payload, dict):
            continue
        public = public_message_text(payload)
        if public is None:
            continue
        role, content = public
        projected.append(
            ConversationMessage(
                id=message.id,
                turn_id=message.turn_id,
                sequence=message.sequence,
                role=role,
                content=content,
                created_at=message.created_at,
            )
        )
    return projected
