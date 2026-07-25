from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.models.idempotency import AgentTurnRun, IdempotencyRecord


def get_idempotency_record(
    db: Session,
    *,
    user_id: UUID,
    method: str,
    route_template: str,
    key_digest: str,
) -> IdempotencyRecord | None:
    statement = select(IdempotencyRecord).where(
        IdempotencyRecord.user_id == user_id,
        IdempotencyRecord.brand_id.is_(None),
        IdempotencyRecord.method == method,
        IdempotencyRecord.route_template == route_template,
        IdempotencyRecord.key_digest == key_digest,
    )
    return db.scalar(statement)


def get_idempotency_record_by_id(
    db: Session,
    record_id: UUID,
) -> IdempotencyRecord | None:
    return db.get(IdempotencyRecord, record_id)


def add_idempotency_record(db: Session, record: IdempotencyRecord) -> None:
    db.add(record)


def add_agent_turn_run(db: Session, run: AgentTurnRun) -> None:
    db.add(run)


def get_agent_turn_run(db: Session, run_id: UUID) -> AgentTurnRun | None:
    return db.get(AgentTurnRun, run_id)


def get_agent_turn_run_by_idempotency_record(
    db: Session,
    record_id: UUID,
) -> AgentTurnRun | None:
    return db.scalar(
        select(AgentTurnRun).where(
            AgentTurnRun.idempotency_record_id == record_id,
        )
    )


def release_conversation_for_agent_turn(
    db: Session,
    run_id: UUID,
) -> None:
    db.execute(
        update(AgentConversation)
        .where(AgentConversation.active_run_id == run_id)
        .values(active_run_id=None, active_run_started_at=None)
        .execution_options(synchronize_session=False)
    )


def delete_expired_idempotency_records(
    db: Session,
    *,
    before: datetime,
) -> None:
    expired_ids = (
        select(IdempotencyRecord.id)
        .where(
            IdempotencyRecord.expires_at <= before,
        )
        .limit(100)
    )
    db.execute(
        delete(IdempotencyRecord).where(
            IdempotencyRecord.id.in_(expired_ids),
        )
    )
