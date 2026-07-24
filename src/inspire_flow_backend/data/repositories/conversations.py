from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.agent_conversation import AgentConversation


def get_conversation(
    db: Session,
    user_id: UUID,
    conversation_id: UUID,
) -> AgentConversation | None:
    return db.scalar(
        select(AgentConversation).where(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
        )
    )


def list_conversations(
    db: Session,
    user_id: UUID,
    *,
    include_archived: bool,
    limit: int,
    offset: int,
) -> tuple[list[AgentConversation], int]:
    filters = [AgentConversation.user_id == user_id]
    if not include_archived:
        filters.append(AgentConversation.archived_at.is_(None))

    total = db.scalar(select(func.count()).select_from(AgentConversation).where(*filters))
    conversations = list(
        db.scalars(
            select(AgentConversation)
            .where(*filters)
            .order_by(
                AgentConversation.updated_at.desc(),
                AgentConversation.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
    )
    return conversations, int(total or 0)


def add_conversation(db: Session, conversation: AgentConversation) -> None:
    db.add(conversation)


def delete_conversation(db: Session, conversation: AgentConversation) -> None:
    db.delete(conversation)
