from functools import lru_cache
from uuid import UUID

from celery.signals import worker_ready
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.config import Settings, get_settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.data.database import SessionLocal
from inspire_flow_backend.data.model_registry import register_models
from inspire_flow_backend.services.transcriptions import (
    claim_transcription_attempt,
    complete_transcription_job,
    fail_transcription_job,
    transcription_spool_path,
)
from inspire_flow_backend.workers.celery_app import celery_app
from inspire_flow_backend.workers.readiness import (
    ReadinessHeartbeat,
    start_readiness_heartbeat,
)
from inspire_flow_backend.workers.stt_engine import (
    AudioTooLongError,
    InvalidAudioError,
    ModelUnavailableError,
    SttEngine,
    create_replicate_whisper_engine,
)

_engine: SttEngine | None = None
_readiness_heartbeat: ReadinessHeartbeat | None = None

register_models()


def get_engine() -> SttEngine:
    global _engine, _readiness_heartbeat
    if _engine is None:
        settings = get_settings()
        _engine = create_replicate_whisper_engine(settings)
        _readiness_heartbeat = start_readiness_heartbeat(settings, _engine.device)
    return _engine


@lru_cache
def get_worker_cipher() -> ContextCipher:
    return ContextCipher.from_settings(get_settings())


@worker_ready.connect
def enqueue_warmup(**kwargs: object) -> None:
    del kwargs
    celery_app.send_task(
        "stt.warmup",
        queue=get_settings().stt_queue,
    )


def run_transcription_job(
    job_id: UUID,
    *,
    session_factory: sessionmaker[Session],
    settings: Settings,
    cipher: ContextCipher,
    engine: SttEngine,
) -> None:
    spool_path = transcription_spool_path(settings, job_id)
    with session_factory() as db:
        job = claim_transcription_attempt(
            db,
            job_id=job_id,
            max_attempts=settings.stt_max_attempts,
        )
        if job is None:
            return
        if job.status == "failed":
            spool_path.unlink(missing_ok=True)
            return
        language = job.language
        use_itn = job.use_itn

    try:
        result = engine.transcribe(
            spool_path,
            language=language,
            use_itn=use_itn,
        )
    except AudioTooLongError:
        error_code = "audio_too_long"
    except InvalidAudioError:
        error_code = "invalid_audio"
    except ModelUnavailableError:
        error_code = "stt_model_unavailable"
    else:
        with session_factory() as db:
            complete_transcription_job(
                db,
                job_id=job_id,
                text=result.text,
                detected_language=result.detected_language,
                duration_seconds=result.duration_seconds,
                emotions=result.emotions,
                audio_events=result.audio_events,
                cipher=cipher,
            )
        spool_path.unlink(missing_ok=True)
        return

    with session_factory() as db:
        fail_transcription_job(db, job_id=job_id, error_code=error_code)
    spool_path.unlink(missing_ok=True)


@celery_app.task(
    name="stt.transcribe",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=get_settings().stt_max_attempts,
)
def transcribe(job_id: str) -> None:
    run_transcription_job(
        UUID(job_id),
        session_factory=SessionLocal,
        settings=get_settings(),
        cipher=get_worker_cipher(),
        engine=get_engine(),
    )


@celery_app.task(name="stt.warmup")
def warmup() -> dict[str, str]:
    engine = get_engine()
    return {"status": "ready", "device": engine.device}
