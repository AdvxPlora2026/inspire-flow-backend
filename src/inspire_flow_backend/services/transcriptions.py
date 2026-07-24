import os
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.errors import (
    AudioTooLargeError,
    SttUnavailableError,
    TranscriptionNotFoundError,
    UnsupportedAudioTypeError,
)
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.models.transcription_job import TranscriptionJob
from inspire_flow_backend.data.repositories import transcriptions as transcription_repository
from inspire_flow_backend.schemas.transcriptions import (
    TranscriptionFailurePublic,
    TranscriptionJobPublic,
    TranscriptionLanguage,
)

_ALLOWED_SUFFIXES = {".flac", ".m4a", ".mp3", ".mp4", ".ogg", ".opus", ".wav", ".webm"}
_ALLOWED_CONTENT_TYPES = {
    "audio/flac",
    "audio/m4a",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/opus",
    "audio/wav",
    "audio/webm",
    "audio/x-m4a",
    "audio/x-wav",
    "video/webm",
}
_FAILURE_MESSAGES = {
    "audio_too_long": "Audio exceeds the configured duration limit",
    "invalid_audio": "Audio could not be decoded",
    "stt_model_unavailable": "Speech transcription model is unavailable",
    "stt_worker_lost": "Speech transcription could not be completed",
}
_UPLOAD_CHUNK_BYTES = 1024 * 1024


class TranscriptionPublisher(Protocol):
    def publish(self, job_id: UUID) -> None: ...


def create_transcription_job(
    db: Session,
    *,
    user_id: UUID,
    source: BinaryIO,
    filename: str | None,
    content_type: str | None,
    language: TranscriptionLanguage,
    use_itn: bool,
    settings: Settings,
    publisher: TranscriptionPublisher,
) -> TranscriptionJob:
    if not settings.stt_enabled:
        raise SttUnavailableError
    _validate_audio_type(filename, content_type)

    job_id = uuid4()
    spool_path = transcription_spool_path(settings, job_id)
    _stage_upload(
        source,
        spool_path,
        max_bytes=settings.stt_max_upload_mib * 1024 * 1024,
    )
    now = utc_now()
    job = TranscriptionJob(
        id=job_id,
        user_id=user_id,
        status="queued",
        language=language,
        use_itn=use_itn,
        attempt_count=0,
        created_at=now,
        updated_at=now,
    )
    transcription_repository.add_transcription_job(db, job)
    db.commit()
    db.refresh(job)
    try:
        publisher.publish(job.id)
    except Exception:
        db.delete(job)
        db.commit()
        spool_path.unlink(missing_ok=True)
        raise SttUnavailableError from None
    return job


def get_transcription_job(
    db: Session,
    *,
    user_id: UUID,
    job_id: UUID,
) -> TranscriptionJob:
    job = transcription_repository.get_transcription_job(db, user_id, job_id)
    if job is None:
        raise TranscriptionNotFoundError
    return job


def claim_transcription_attempt(
    db: Session,
    *,
    job_id: UUID,
    max_attempts: int,
) -> TranscriptionJob | None:
    job = transcription_repository.get_transcription_job_by_id(db, job_id)
    if job is None or job.status in {"succeeded", "failed"}:
        return None
    now = utc_now()
    if job.attempt_count >= max_attempts:
        job.status = "failed"
        job.error_code = "stt_worker_lost"
        job.completed_at = now
        job.updated_at = now
    else:
        job.status = "running"
        job.attempt_count += 1
        job.started_at = now
        job.updated_at = now
    db.commit()
    db.refresh(job)
    return job


def complete_transcription_job(
    db: Session,
    *,
    job_id: UUID,
    text: str,
    detected_language: str | None,
    duration_seconds: float,
    cipher: ContextCipher,
) -> None:
    job = transcription_repository.get_transcription_job_by_id(db, job_id)
    if job is None or job.status in {"succeeded", "failed"}:
        return
    now = utc_now()
    job.status = "succeeded"
    job.transcript_ciphertext = cipher.encrypt_text(text)
    job.detected_language = detected_language
    job.duration_seconds = duration_seconds
    job.error_code = None
    job.completed_at = now
    job.updated_at = now
    db.commit()


def fail_transcription_job(
    db: Session,
    *,
    job_id: UUID,
    error_code: str,
) -> None:
    job = transcription_repository.get_transcription_job_by_id(db, job_id)
    if job is None or job.status in {"succeeded", "failed"}:
        return
    now = utc_now()
    job.status = "failed"
    job.error_code = error_code
    job.completed_at = now
    job.updated_at = now
    db.commit()


def build_transcription_public(
    job: TranscriptionJob,
    cipher: ContextCipher,
) -> TranscriptionJobPublic:
    text = (
        cipher.decrypt_text(job.transcript_ciphertext)
        if job.transcript_ciphertext is not None
        else None
    )
    error = None
    if job.error_code is not None:
        error = TranscriptionFailurePublic(
            code=job.error_code,
            message=_FAILURE_MESSAGES.get(
                job.error_code,
                "Speech transcription could not be completed",
            ),
        )
    return TranscriptionJobPublic(
        id=job.id,
        status=job.status,
        language=job.language,
        use_itn=job.use_itn,
        text=text,
        detected_language=job.detected_language,
        duration_seconds=job.duration_seconds,
        error=error,
        attempt_count=job.attempt_count,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def transcription_spool_path(settings: Settings, job_id: UUID) -> Path:
    return settings.stt_spool_dir / f"{job_id}.audio"


def _validate_audio_type(filename: str | None, content_type: str | None) -> None:
    suffix = Path(filename or "").suffix.casefold()
    normalized_content_type = (content_type or "").split(";", 1)[0].strip().casefold()
    if suffix not in _ALLOWED_SUFFIXES or normalized_content_type not in _ALLOWED_CONTENT_TYPES:
        raise UnsupportedAudioTypeError


def _stage_upload(source: BinaryIO, destination: Path, *, max_bytes: int) -> None:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        destination.parent.chmod(0o700)
    except OSError:
        pass
    part_path = destination.with_suffix(".part")
    total = 0
    try:
        descriptor = os.open(
            part_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as staged:
            while chunk := source.read(_UPLOAD_CHUNK_BYTES):
                total += len(chunk)
                if total > max_bytes:
                    raise AudioTooLargeError
                staged.write(chunk)
            staged.flush()
            os.fsync(staged.fileno())
        os.replace(part_path, destination)
    except Exception:
        part_path.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
