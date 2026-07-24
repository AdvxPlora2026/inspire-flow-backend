from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.agent_message import AgentMessage


def list_messages_after(
    db: Session,
    conversation_id: UUID,
    *,
    sequence: int,
    limit: int | None = None,
) -> list[AgentMessage]:
    statement = (
        select(AgentMessage)
        .where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.sequence > sequence,
        )
        .order_by(AgentMessage.sequence.desc() if limit is not None else AgentMessage.sequence)
    )
    if limit is not None:
        statement = statement.limit(limit)
    messages = list(db.scalars(statement))
    if limit is not None:
        messages.reverse()
    return messages


def list_public_message_rows_after(
    db: Session,
    conversation_id: UUID,
    *,
    sequence: int,
    limit: int,
) -> list[AgentMessage]:
    return list(
        db.scalars(
            select(AgentMessage)
            .where(
                AgentMessage.conversation_id == conversation_id,
                AgentMessage.sequence > sequence,
                AgentMessage.role.in_(("user", "assistant")),
            )
            .order_by(AgentMessage.sequence)
            .limit(limit)
        )
    )


def get_latest_message(
    db: Session,
    conversation_id: UUID,
) -> AgentMessage | None:
    return db.scalar(
        select(AgentMessage)
        .where(AgentMessage.conversation_id == conversation_id)
        .order_by(AgentMessage.sequence.desc())
        .limit(1)
    )


def get_message(
    db: Session,
    conversation_id: UUID,
    message_id: UUID,
) -> AgentMessage | None:
    return db.scalar(
        select(AgentMessage).where(
            AgentMessage.id == message_id,
            AgentMessage.conversation_id == conversation_id,
        )
    )


def list_turn_messages(
    db: Session,
    conversation_id: UUID,
    turn_id: UUID,
) -> list[AgentMessage]:
    return list(
        db.scalars(
            select(AgentMessage)
            .where(
                AgentMessage.conversation_id == conversation_id,
                AgentMessage.turn_id == turn_id,
            )
            .order_by(AgentMessage.sequence)
        )
    )


def add_messages(db: Session, messages: list[AgentMessage]) -> None:
    db.add_all(messages)


def delete_message(db: Session, message: AgentMessage) -> None:
    db.delete(message)


def delete_all_messages(db: Session, conversation_id: UUID) -> None:
    db.execute(delete(AgentMessage).where(AgentMessage.conversation_id == conversation_id))
