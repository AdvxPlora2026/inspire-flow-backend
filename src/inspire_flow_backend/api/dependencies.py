from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from inspire_flow_backend.core.config import Settings, get_settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.errors import InvalidSessionError
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.services.agent.runtime import (
    AgentRuntime,
    create_agent_runtime,
)
from inspire_flow_backend.services.agent.streaming import RuntimeFactory
from inspire_flow_backend.services.idempotency import prepare_idempotency
from inspire_flow_backend.services.injective import (
    InjectiveProvider,
    create_injective_provider,
)
from inspire_flow_backend.services.sessions import (
    AuthenticatedSession,
    resolve_session,
)
from inspire_flow_backend.services.transcriptions import TranscriptionPublisher

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_context_cipher() -> ContextCipher:
    return ContextCipher.from_settings(get_settings())


async def get_agent_runtime() -> AsyncGenerator[AgentRuntime]:
    runtime = create_agent_runtime()
    try:
        yield runtime
    finally:
        await runtime.aclose()


def get_agent_stream_runtime_factory() -> RuntimeFactory:
    return create_agent_runtime


async def get_current_session(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
) -> AuthenticatedSession:
    if (
        credentials is None
        or credentials.scheme.casefold() != "bearer"
        or not credentials.credentials
    ):
        raise InvalidSessionError
    authenticated = resolve_session(db, credentials.credentials)
    await prepare_idempotency(
        request,
        db=db,
        user_id=authenticated.user.id,
        key=idempotency_key,
        cipher=cipher,
        processing_timeout_seconds=settings.agent_run_lock_ttl_seconds,
    )
    return authenticated


def get_optional_session(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: Annotated[Session, Depends(get_db_session)],
) -> AuthenticatedSession | None:
    if credentials is None:
        return None
    if credentials.scheme.casefold() != "bearer" or not credentials.credentials:
        raise InvalidSessionError
    return resolve_session(db, credentials.credentials)


def get_transcription_publisher(request: Request) -> TranscriptionPublisher:
    publisher = getattr(request.app.state, "transcription_publisher", None)
    if publisher is None:
        from inspire_flow_backend.workers.celery_app import CeleryTranscriptionPublisher

        publisher = CeleryTranscriptionPublisher()
        request.app.state.transcription_publisher = publisher
    return publisher


def get_injective_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> InjectiveProvider | None:
    return create_injective_provider(settings)
