from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.commercial import (
    ChainTransaction,
    CommercialTask,
    CommercialTaskSplit,
    CommercialTaskSubmission,
)


def add_task(db: Session, task: CommercialTask) -> None:
    db.add(task)


def add_split(db: Session, split: CommercialTaskSplit) -> None:
    db.add(split)


def add_submission(db: Session, submission: CommercialTaskSubmission) -> None:
    db.add(submission)


def add_transaction(db: Session, transaction: ChainTransaction) -> None:
    db.add(transaction)


def get_task(
    db: Session,
    user_id: UUID,
    task_id: UUID,
) -> CommercialTask | None:
    return db.scalar(
        select(CommercialTask).where(
            CommercialTask.id == task_id,
            CommercialTask.user_id == user_id,
        )
    )


def list_splits(db: Session, task_id: UUID) -> list[CommercialTaskSplit]:
    return list(
        db.scalars(
            select(CommercialTaskSplit)
            .where(CommercialTaskSplit.task_id == task_id)
            .order_by(
                CommercialTaskSplit.sort_order.asc(),
                CommercialTaskSplit.id.asc(),
            )
        )
    )


def list_submissions(db: Session, task_id: UUID) -> list[CommercialTaskSubmission]:
    return list(
        db.scalars(
            select(CommercialTaskSubmission)
            .where(CommercialTaskSubmission.task_id == task_id)
            .order_by(
                CommercialTaskSubmission.created_at.asc(),
                CommercialTaskSubmission.id.asc(),
            )
        )
    )


def list_transactions(db: Session, task_id: UUID) -> list[ChainTransaction]:
    return list(
        db.scalars(
            select(ChainTransaction)
            .where(ChainTransaction.task_id == task_id)
            .order_by(
                ChainTransaction.created_at.asc(),
                ChainTransaction.id.asc(),
            )
        )
    )
