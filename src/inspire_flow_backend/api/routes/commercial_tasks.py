from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import (
    get_current_session,
    get_injective_provider,
)
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.commercial import (
    CommercialSubmissionCreate,
    CommercialSubmissionPublic,
    CommercialTaskCreate,
    CommercialTaskProof,
    CommercialTaskPublic,
)
from inspire_flow_backend.schemas.errors import ErrorResponse
from inspire_flow_backend.services import commercial_tasks as commercial_task_service
from inspire_flow_backend.services.idempotency import retain_idempotency_until
from inspire_flow_backend.services.injective import InjectiveProvider
from inspire_flow_backend.services.sessions import AuthenticatedSession

router = APIRouter()

TASK_RESPONSES = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}
TRANSITION_RESPONSES = {
    **TASK_RESPONSES,
    409: {"model": ErrorResponse},
}


@router.post(
    "",
    response_model=CommercialTaskPublic,
    status_code=status.HTTP_201_CREATED,
    responses={
        **TASK_RESPONSES,
        422: {"model": ErrorResponse},
    },
)
def create_commercial_task(
    payload: CommercialTaskCreate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[InjectiveProvider | None, Depends(get_injective_provider)],
) -> CommercialTaskPublic:
    return commercial_task_service.create_commercial_task(
        db,
        authenticated.user.id,
        payload,
        provider,
    )


@router.post(
    "/{task_id}/submissions",
    response_model=CommercialSubmissionPublic,
    status_code=status.HTTP_201_CREATED,
    responses={
        **TRANSITION_RESPONSES,
        422: {"model": ErrorResponse},
    },
)
def create_submission(
    task_id: UUID,
    payload: CommercialSubmissionCreate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[InjectiveProvider | None, Depends(get_injective_provider)],
) -> CommercialSubmissionPublic:
    return commercial_task_service.create_submission(
        db,
        authenticated.user.id,
        task_id,
        payload,
        provider,
    )


@router.post(
    "/{task_id}/authorize",
    response_model=CommercialTaskPublic,
    responses=TRANSITION_RESPONSES,
)
def authorize_task(
    task_id: UUID,
    request: Request,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[InjectiveProvider | None, Depends(get_injective_provider)],
) -> CommercialTaskPublic:
    task = commercial_task_service.authorize_task(
        db,
        authenticated.user.id,
        task_id,
        provider,
    )
    retain_idempotency_until(request, task.deadline + timedelta(hours=24))
    return task


@router.post(
    "/{task_id}/settle",
    response_model=CommercialTaskPublic,
    responses=TRANSITION_RESPONSES,
)
def settle_task(
    task_id: UUID,
    request: Request,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[InjectiveProvider | None, Depends(get_injective_provider)],
) -> CommercialTaskPublic:
    task = commercial_task_service.settle_task(
        db,
        authenticated.user.id,
        task_id,
        provider,
    )
    retain_idempotency_until(request, task.deadline + timedelta(hours=24))
    return task


@router.get(
    "/{task_id}/proof",
    response_model=CommercialTaskProof,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def read_task_proof(
    task_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    provider: Annotated[InjectiveProvider | None, Depends(get_injective_provider)],
) -> CommercialTaskProof:
    return commercial_task_service.get_task_proof(
        db,
        authenticated.user.id,
        task_id,
        provider,
    )
