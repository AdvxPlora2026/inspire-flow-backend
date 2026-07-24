from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from inspire_flow_backend.data.models.transcription_job import TranscriptionJob


def add_transcription_job(db: Session, job: TranscriptionJob) -> None:
    db.add(job)


def get_transcription_job(
    db: Session,
    user_id: UUID,
    job_id: UUID,
) -> TranscriptionJob | None:
    return db.scalar(
        select(TranscriptionJob).where(
            TranscriptionJob.id == job_id,
            TranscriptionJob.user_id == user_id,
        )
    )


def get_transcription_job_by_id(
    db: Session,
    job_id: UUID,
) -> TranscriptionJob | None:
    return db.get(TranscriptionJob, job_id)


def delete_transcription_job(db: Session, job: TranscriptionJob) -> None:
    db.delete(job)
