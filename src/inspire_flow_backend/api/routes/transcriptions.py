from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.orm import Session

from inspire_flow_backend.api.dependencies import (
    get_context_cipher,
    get_current_session,
    get_transcription_publisher,
)
from inspire_flow_backend.core.config import Settings, get_settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.data.database import get_db_session
from inspire_flow_backend.schemas.errors import ErrorResponse
from inspire_flow_backend.schemas.transcriptions import (
    TranscriptionJobPublic,
    TranscriptionLanguage,
)
from inspire_flow_backend.services.sessions import AuthenticatedSession
from inspire_flow_backend.services.transcriptions import (
    TranscriptionPublisher,
    build_transcription_public,
    create_transcription_job,
    get_transcription_job,
)

router = APIRouter()


@router.post(
    "",
    response_model=TranscriptionJobPublic,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def submit_transcription(
    response: Response,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    publisher: Annotated[TranscriptionPublisher, Depends(get_transcription_publisher)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
    file: Annotated[UploadFile, File()],
    language: Annotated[TranscriptionLanguage, Form()] = "auto",
    use_itn: Annotated[bool, Form()] = True,
) -> TranscriptionJobPublic:
    job = create_transcription_job(
        db,
        user_id=authenticated.user.id,
        source=file.file,
        filename=file.filename,
        content_type=file.content_type,
        language=language,
        use_itn=use_itn,
        settings=settings,
        publisher=publisher,
    )
    response.headers["Location"] = f"{settings.api_v1_prefix}/transcriptions/{job.id}"
    return build_transcription_public(job, cipher)


@router.get(
    "/{job_id}",
    response_model=TranscriptionJobPublic,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def read_transcription(
    job_id: UUID,
    authenticated: Annotated[AuthenticatedSession, Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db_session)],
    cipher: Annotated[ContextCipher, Depends(get_context_cipher)],
) -> TranscriptionJobPublic:
    job = get_transcription_job(
        db,
        user_id=authenticated.user.id,
        job_id=job_id,
    )
    return build_transcription_public(job, cipher)
