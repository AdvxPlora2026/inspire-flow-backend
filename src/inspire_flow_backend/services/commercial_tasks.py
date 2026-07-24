import json
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from inspire_flow_backend.core.errors import (
    CommercialTaskNotFoundError,
    InjectiveUnavailableError,
    ProjectNotFoundError,
    SequenceConflictError,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.commercial import (
    ChainTransaction,
    CommercialTask,
    CommercialTaskSplit,
    CommercialTaskSubmission,
)
from inspire_flow_backend.data.repositories import commercial as commercial_repository
from inspire_flow_backend.data.repositories import projects as project_repository
from inspire_flow_backend.schemas.commercial import (
    Budget,
    ChainTransactionPublic,
    CommercialSubmissionCreate,
    CommercialSubmissionPublic,
    CommercialTaskCreate,
    CommercialTaskProof,
    CommercialTaskPublic,
)
from inspire_flow_backend.schemas.commercial import (
    CommercialTaskSplit as CommercialTaskSplitSchema,
)
from inspire_flow_backend.services.injective import (
    ChainBroadcastError,
    InjectiveProvider,
)

ACTION_TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "escrow_funded": (frozenset({"created"}), "escrow_funded"),
    "submission_recorded": (
        frozenset({"escrow_funded", "submission_recorded"}),
        "submission_recorded",
    ),
    "authorization_activated": (
        frozenset({"submission_recorded"}),
        "authorization_activated",
    ),
    "settlement_released": (
        frozenset({"authorization_activated"}),
        "settlement_released",
    ),
}


def create_commercial_task(
    db: Session,
    user_id: UUID,
    payload: CommercialTaskCreate,
    provider: InjectiveProvider | None,
) -> CommercialTaskPublic:
    _require_provider(provider)
    project = project_repository.get_project(db, user_id, payload.project_id)
    if project is None:
        raise ProjectNotFoundError
    now = utc_now()
    task = CommercialTask(
        id=uuid4(),
        user_id=user_id,
        project_id=payload.project_id,
        title=payload.title,
        budget_amount=payload.budget.amount,
        budget_denom=payload.budget.denom,
        deadline=payload.deadline,
        status="escrow_funded",
        created_at=now,
        updated_at=now,
    )
    commercial_repository.add_task(db, task)
    db.flush()
    for sort_order, split in enumerate(payload.splits):
        commercial_repository.add_split(
            db,
            CommercialTaskSplit(
                task_id=task.id,
                party_id=split.party_id,
                bps=split.bps,
                sort_order=sort_order,
            ),
        )
    transaction = _prepare_transaction(
        db,
        provider,
        task_id=task.id,
        action="escrow_funded",
        amount=payload.budget.amount,
        denom=payload.budget.denom,
    )
    db.commit()
    _attempt_broadcast(db, provider, transaction)
    db.refresh(task)
    return _serialize_task(db, task)


def create_submission(
    db: Session,
    user_id: UUID,
    task_id: UUID,
    payload: CommercialSubmissionCreate,
    provider: InjectiveProvider | None,
) -> CommercialSubmissionPublic:
    _require_provider(provider)
    task = _get_owned_task(db, user_id, task_id)
    _apply_transition(task, "submission_recorded")
    submission = CommercialTaskSubmission(
        task_id=task.id,
        artifact_id=payload.artifact_id,
        artifact_sha256=payload.artifact_sha256,
        delivery_url=str(payload.delivery_url),
        created_at=utc_now(),
    )
    commercial_repository.add_submission(db, submission)
    transaction = _prepare_transaction(
        db,
        provider,
        task_id=task.id,
        action="submission_recorded",
        artifact_sha256=payload.artifact_sha256,
    )
    db.commit()
    _attempt_broadcast(db, provider, transaction)
    db.refresh(submission)
    return CommercialSubmissionPublic.model_validate(submission)


def authorize_task(
    db: Session,
    user_id: UUID,
    task_id: UUID,
    provider: InjectiveProvider | None,
) -> CommercialTaskPublic:
    return _transition_task(db, user_id, task_id, provider, "authorization_activated")


def settle_task(
    db: Session,
    user_id: UUID,
    task_id: UUID,
    provider: InjectiveProvider | None,
) -> CommercialTaskPublic:
    return _transition_task(db, user_id, task_id, provider, "settlement_released")


def get_task_proof(
    db: Session,
    user_id: UUID,
    task_id: UUID,
    provider: InjectiveProvider | None,
) -> CommercialTaskProof:
    task = _get_owned_task(db, user_id, task_id)
    if provider is not None:
        _refresh_transactions(db, provider, task_id)
    submissions = commercial_repository.list_submissions(db, task_id)
    transactions = commercial_repository.list_transactions(db, task_id)
    return CommercialTaskProof(
        task=_serialize_task(db, task),
        submissions=[
            CommercialSubmissionPublic.model_validate(submission) for submission in submissions
        ],
        transactions=[
            ChainTransactionPublic.model_validate(transaction) for transaction in transactions
        ],
    )


def _transition_task(
    db: Session,
    user_id: UUID,
    task_id: UUID,
    provider: InjectiveProvider | None,
    action: str,
) -> CommercialTaskPublic:
    _require_provider(provider)
    task = _get_owned_task(db, user_id, task_id)
    _apply_transition(task, action)
    amount: str | None = None
    denom: str | None = None
    if action == "settlement_released":
        amount = task.budget_amount
        denom = task.budget_denom
    transaction = _prepare_transaction(
        db,
        provider,
        task_id=task.id,
        action=action,
        amount=amount,
        denom=denom,
    )
    db.commit()
    _attempt_broadcast(db, provider, transaction)
    db.refresh(task)
    return _serialize_task(db, task)


def _require_provider(provider: InjectiveProvider | None) -> InjectiveProvider:
    if provider is None:
        raise InjectiveUnavailableError
    return provider


def _get_owned_task(db: Session, user_id: UUID, task_id: UUID) -> CommercialTask:
    task = commercial_repository.get_task(db, user_id, task_id)
    if task is None:
        raise CommercialTaskNotFoundError
    return task


def _apply_transition(task: CommercialTask, action: str) -> None:
    allowed_statuses, next_status = ACTION_TRANSITIONS[action]
    if task.status not in allowed_statuses:
        raise SequenceConflictError
    task.status = next_status
    task.updated_at = utc_now()


def _prepare_transaction(
    db: Session,
    provider: InjectiveProvider,
    *,
    task_id: UUID,
    action: str,
    amount: str | None = None,
    denom: str | None = None,
    artifact_sha256: str | None = None,
) -> ChainTransaction:
    memo_facts: dict[str, str] = {
        "action": action,
        "task_id": str(task_id),
    }
    if artifact_sha256 is not None:
        memo_facts["artifact_sha256"] = artifact_sha256
    if amount is not None and denom is not None:
        memo_facts["amount"] = amount
        memo_facts["denom"] = denom
    now = utc_now()
    transaction = ChainTransaction(
        task_id=task_id,
        action=action,
        status="prepared",
        network=provider.network,
        chain_id=provider.chain_id,
        memo=json.dumps(memo_facts, separators=(",", ":"), sort_keys=True),
        artifact_sha256=artifact_sha256,
        amount=amount,
        denom=denom,
        created_at=now,
        updated_at=now,
    )
    commercial_repository.add_transaction(db, transaction)
    return transaction


def _attempt_broadcast(
    db: Session,
    provider: InjectiveProvider,
    transaction: ChainTransaction,
) -> None:
    try:
        broadcast = provider.broadcast(transaction.memo)
    except ChainBroadcastError as error:
        transaction.status = "failed"
        transaction.failure_reason = error.reason
        transaction.retryable = error.retryable
        transaction.updated_at = utc_now()
        db.commit()
        return
    transaction.status = "broadcast"
    transaction.chain_id = broadcast.chain_id
    transaction.transaction_hash = broadcast.transaction_hash
    transaction.nonce = broadcast.nonce
    transaction.explorer_url = broadcast.explorer_url
    transaction.failure_reason = None
    transaction.retryable = None
    transaction.submitted_at = utc_now()
    transaction.updated_at = utc_now()
    db.commit()


def _refresh_transactions(
    db: Session,
    provider: InjectiveProvider,
    task_id: UUID,
) -> None:
    changed = False
    for transaction in commercial_repository.list_transactions(db, task_id):
        if transaction.status == "prepared" or (
            transaction.status == "failed" and transaction.retryable is True
        ):
            _attempt_broadcast(db, provider, transaction)
        if transaction.status == "broadcast" and transaction.transaction_hash is not None:
            confirmation = provider.get_transaction_status(
                transaction.transaction_hash, nonce=transaction.nonce
            )
            if confirmation == "confirmed":
                transaction.status = "confirmed"
                transaction.confirmed_at = utc_now()
                transaction.updated_at = utc_now()
                changed = True
            elif confirmation == "failed":
                transaction.status = "failed"
                transaction.failure_reason = "Transaction reverted on chain"
                transaction.retryable = False
                transaction.updated_at = utc_now()
                changed = True
    if changed:
        db.commit()


def _serialize_task(db: Session, task: CommercialTask) -> CommercialTaskPublic:
    splits = commercial_repository.list_splits(db, task.id)
    return CommercialTaskPublic(
        id=task.id,
        project_id=task.project_id,
        user_id=task.user_id,
        title=task.title,
        budget=Budget(amount=task.budget_amount, denom=task.budget_denom),
        deadline=task.deadline,
        status=task.status,  # type: ignore[arg-type]
        splits=[
            CommercialTaskSplitSchema(party_id=split.party_id, bps=split.bps) for split in splits
        ],
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
