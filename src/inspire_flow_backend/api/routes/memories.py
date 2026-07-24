from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import (
    get_context_cipher,
    get_current_session,
)
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.errors import ErrorResponse
from inspire_flow_backend.schemas.memories import (
    MemoryCategory,
    MemoryStatus,
    UserMemoryCreate,
    UserMemoryPage,
    UserMemoryPublic,
    UserMemoryUpdate,
)
from inspire_flow_backend.services.memories import (
    create_manual_memory,
    delete_memory,
    get_public_memory,
    list_public_memories,
    update_memory,
)
from inspire_flow_backend.services.sessions import AuthenticatedSession

router = APIRouter()


@router.post(
    "",
    response_model=UserMemoryPublic,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def create_current_user_memory(
    payload: UserMemoryCreate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
) -> UserMemoryPublic:
    return create_manual_memory(db, authenticated.user.id, payload, cipher)


@router.get(
    "",
    response_model=UserMemoryPage,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def read_current_user_memories(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
    memory_status: Annotated[MemoryStatus | None, Query(alias="status")] = None,
    category: MemoryCategory | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UserMemoryPage:
    return list_public_memories(
        db,
        authenticated.user.id,
        status=memory_status,
        category=category,
        limit=limit,
        offset=offset,
        cipher=cipher,
    )


@router.get(
    "/{memory_id}",
    response_model=UserMemoryPublic,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def read_current_user_memory(
    memory_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
) -> UserMemoryPublic:
    return get_public_memory(db, authenticated.user.id, memory_id, cipher)


@router.patch(
    "/{memory_id}",
    response_model=UserMemoryPublic,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def patch_current_user_memory(
    memory_id: UUID,
    payload: UserMemoryUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
) -> UserMemoryPublic:
    return update_memory(
        db,
        authenticated.user.id,
        memory_id,
        payload,
        cipher,
    )


@router.delete(
    "/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def delete_current_user_memory(
    memory_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> Response:
    delete_memory(db, authenticated.user.id, memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
