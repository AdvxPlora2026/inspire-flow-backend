from uuid import UUID

from celery import Celery

from inspire_flow_backend.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "inspire_flow_backend",
    broker=settings.stt_broker_url,
)
celery_app.conf.update(
    task_routes={"stt.*": {"queue": settings.stt_queue}},
    task_default_queue=settings.stt_queue,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=settings.stt_soft_time_limit_seconds,
    task_time_limit=settings.stt_hard_time_limit_seconds,
    broker_transport_options={
        "visibility_timeout": settings.stt_hard_time_limit_seconds + 300,
    },
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    imports=("inspire_flow_backend.workers.stt_tasks",),
)


class CeleryTranscriptionPublisher:
    def publish(self, job_id: UUID) -> None:
        celery_app.send_task(
            "stt.transcribe",
            args=[str(job_id)],
            task_id=str(job_id),
            queue=settings.stt_queue,
        )
