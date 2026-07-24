from datetime import timedelta
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import (
    get_agent_runtime,
    get_agent_stream_runtime_factory,
    get_context_cipher,
    get_current_session,
)
from inspire_flow_backend.core.config import Settings, get_settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.errors import IdempotencyKeyRequiredError
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.conversations import (
    AgentTurnPublic,
    ConversationCreate,
    ConversationMessageCreate,
    ConversationMessagePage,
    ConversationPage,
    ConversationPublic,
    ConversationUpdate,
)
from inspire_flow_backend.schemas.errors import (
    ErrorResponse,
    ResourceImpactErrorResponse,
)
from inspire_flow_backend.services.agent.conversation import run_conversation_turn
from inspire_flow_backend.services.agent.runtime import AgentRuntime
from inspire_flow_backend.services.agent.streaming import (
    AgentStreamManager,
    RuntimeFactory,
)
from inspire_flow_backend.services.conversations import (
    create_conversation,
    delete_conversation,
    ensure_conversation_turn_available,
    get_conversation,
    list_conversation_messages,
    list_conversations,
    update_conversation,
)
from inspire_flow_backend.services.sessions import AuthenticatedSession

router = APIRouter()


@router.post(
    "",
    response_model=ConversationPublic,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def create_user_conversation(
    payload: ConversationCreate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> ConversationPublic:
    conversation = create_conversation(db, authenticated.user.id, payload)
    return ConversationPublic.model_validate(conversation)


@router.get(
    "",
    response_model=ConversationPage,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def read_user_conversations(
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    include_archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationPage:
    return list_conversations(
        db,
        authenticated.user.id,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationPublic,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def read_user_conversation(
    conversation_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> ConversationPublic:
    conversation = get_conversation(db, authenticated.user.id, conversation_id)
    return ConversationPublic.model_validate(conversation)


@router.patch(
    "/{conversation_id}",
    response_model=ConversationPublic,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def patch_user_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
) -> ConversationPublic:
    conversation = update_conversation(
        db,
        authenticated.user.id,
        conversation_id,
        payload,
    )
    return ConversationPublic.model_validate(conversation)


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ResourceImpactErrorResponse},
    },
)
def delete_user_conversation(
    conversation_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    delete_orphan_inspirations: bool = False,
) -> Response:
    delete_conversation(
        db,
        authenticated.user.id,
        conversation_id,
        delete_orphan_inspirations=delete_orphan_inspirations,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{conversation_id}/messages",
    response_model=ConversationMessagePage,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def read_user_conversation_messages(
    conversation_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ConversationMessagePage:
    return list_conversation_messages(
        db,
        authenticated.user.id,
        conversation_id,
        after_sequence=after_sequence,
        limit=limit,
        cipher=cipher,
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=AgentTurnPublic,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def create_user_conversation_message(
    conversation_id: UUID,
    payload: ConversationMessageCreate,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
    runtime: Annotated[AgentRuntime, Depends(get_agent_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentTurnPublic:
    """Continue the persistent Agent session ID owned by the bearer-authenticated user."""
    turn = await run_conversation_turn(
        db,
        user=authenticated.user,
        conversation_id=conversation_id,
        content=payload.content,
        runtime=runtime,
        cipher=cipher,
        settings=settings,
    )
    return AgentTurnPublic.model_validate(turn)


@router.post(
    "/{conversation_id}/messages/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Server-sent Agent turn events",
        },
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def stream_user_conversation_message(
    conversation_id: UUID,
    payload: ConversationMessageCreate,
    request: Request,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
    runtime_factory: Annotated[
        RuntimeFactory,
        Depends(get_agent_stream_runtime_factory),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    ensure_conversation_turn_available(
        db,
        user_id=authenticated.user.id,
        conversation_id=conversation_id,
        stale_before=utc_now() - timedelta(seconds=settings.agent_run_lock_ttl_seconds),
    )
    idempotency_record_id = getattr(
        request.state,
        "idempotency_record_id",
        None,
    )
    if not isinstance(idempotency_record_id, UUID):
        raise IdempotencyKeyRequiredError
    manager = cast(
        AgentStreamManager,
        request.app.state.agent_stream_manager,
    )
    handle = manager.start(
        engine=cast(Engine, db.get_bind()),
        user_id=authenticated.user.id,
        conversation_id=conversation_id,
        content=payload.content,
        idempotency_record_id=idempotency_record_id,
        runtime_factory=runtime_factory,
        cipher=cipher,
        settings=settings,
    )
    return StreamingResponse(
        handle.events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
