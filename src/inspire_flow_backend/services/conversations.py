from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.errors import (
    ConversationArchivedError,
    ConversationBusyError,
    ConversationNotFoundError,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.data.models.user_memory import UserMemory
from inspire_flow_backend.data.repositories import conversations as conversation_repository
from inspire_flow_backend.data.repositories.messages import (
    list_public_message_rows_after,
)
from inspire_flow_backend.schemas.conversations import (
    ConversationCreate,
    ConversationMessagePage,
    ConversationMessagePublic,
    ConversationPage,
    ConversationPublic,
    ConversationUpdate,
)
from inspire_flow_backend.services.agent.session_items import public_message_text


def create_conversation(
    db: Session,
    user_id: UUID,
    payload: ConversationCreate,
) -> AgentConversation:
    now = utc_now()
    conversation = AgentConversation(
        user_id=user_id,
        title=payload.title,
        summary_through_sequence=0,
        next_sequence=1,
        created_at=now,
        updated_at=now,
    )
    conversation_repository.add_conversation(db, conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def get_conversation(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
) -> AgentConversation:
    conversation = conversation_repository.get_conversation(
        db,
        user_id,
        conversation_id,
    )
    if conversation is None:
        raise ConversationNotFoundError
    return conversation


def list_conversations(
    db: Session,
    user_id: UUID,
    *,
    include_archived: bool,
    limit: int,
    offset: int,
) -> ConversationPage:
    conversations, total = conversation_repository.list_conversations(
        db,
        user_id,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return ConversationPage(
        items=[ConversationPublic.model_validate(conversation) for conversation in conversations],
        total=total,
        limit=limit,
        offset=offset,
    )


def update_conversation(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
    payload: ConversationUpdate,
) -> AgentConversation:
    conversation = get_conversation(db, user_id, conversation_id)
    changed = False

    if "title" in payload.model_fields_set and conversation.title != payload.title:
        conversation.title = payload.title
        changed = True
    if "archived" in payload.model_fields_set:
        archived_at = utc_now() if payload.archived else None
        if conversation.archived != payload.archived:
            conversation.archived_at = archived_at
            changed = True

    if not changed:
        return conversation
    conversation.updated_at = utc_now()
    db.commit()
    db.refresh(conversation)
    return conversation


def delete_conversation(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
) -> None:
    conversation = get_conversation(db, user_id, conversation_id)
    source_memories = list(
        db.scalars(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.source_conversation_id == conversation_id,
            )
        )
    )
    deleted_at = utc_now()
    for memory in source_memories:
        if memory.origin == "automatic" and not memory.user_edited and not memory.is_pinned:
            db.delete(memory)
            continue
        memory.source_conversation_id = None
        memory.source_message_id = None
        memory.source_deleted_at = deleted_at
        memory.updated_at = deleted_at

    conversation_repository.delete_conversation(db, conversation)
    db.commit()


def claim_conversation_run(
    db: Session,
    *,
    user_id: UUID,
    conversation_id: UUID,
    run_id: UUID,
    stale_before: datetime,
) -> AgentConversation:
    conversation = get_conversation(db, user_id, conversation_id)
    if conversation.archived:
        raise ConversationArchivedError

    result = db.execute(
        update(AgentConversation)
        .where(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
            AgentConversation.archived_at.is_(None),
            or_(
                AgentConversation.active_run_id.is_(None),
                AgentConversation.active_run_started_at.is_(None),
                AgentConversation.active_run_started_at < stale_before,
            ),
        )
        .values(
            active_run_id=run_id,
            active_run_started_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        current = get_conversation(db, user_id, conversation_id)
        if current.archived:
            raise ConversationArchivedError
        raise ConversationBusyError

    db.commit()
    db.refresh(conversation)
    return conversation


def release_conversation_run(
    db: Session,
    *,
    user_id: UUID,
    conversation_id: UUID,
    run_id: UUID,
) -> None:
    db.execute(
        update(AgentConversation)
        .where(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
            AgentConversation.active_run_id == run_id,
        )
        .values(active_run_id=None, active_run_started_at=None)
        .execution_options(synchronize_session="fetch")
    )
    db.commit()


def list_conversation_messages(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
    *,
    after_sequence: int,
    limit: int,
    cipher: ContextCipher,
) -> ConversationMessagePage:
    get_conversation(db, user_id, conversation_id)
    messages = list_public_message_rows_after(
        db,
        conversation_id,
        sequence=after_sequence,
        limit=limit + 1,
    )
    projected: list[ConversationMessagePublic] = []
    for message in messages:
        public = _to_public_message(message, cipher)
        if public is not None:
            projected.append(public)

    has_more = len(projected) > limit
    page_items = projected[:limit]
    next_cursor = page_items[-1].sequence if has_more and page_items else None
    return ConversationMessagePage(
        items=page_items,
        next_cursor=next_cursor,
        limit=limit,
    )


def _to_public_message(
    message: AgentMessage,
    cipher: ContextCipher,
) -> ConversationMessagePublic | None:
    payload = cipher.decrypt_json(message.payload_ciphertext)
    if not isinstance(payload, dict):
        return None
    projected = public_message_text(payload)
    if projected is None:
        return None
    role, content = projected
    return ConversationMessagePublic(
        id=message.id,
        turn_id=message.turn_id,
        sequence=message.sequence,
        role=role,
        content=content,
        created_at=message.created_at,
    )
