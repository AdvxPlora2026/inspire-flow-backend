import sys
from uuid import uuid4

from inspire_flow_backend.workers import celery_app as celery_module


def test_celery_app_routes_only_stt_tasks_to_the_dedicated_queue() -> None:
    settings = celery_module.settings
    configuration = celery_module.celery_app.conf

    assert configuration.task_routes["stt.*"]["queue"] == settings.stt_queue
    assert configuration.task_acks_late is True
    assert configuration.task_reject_on_worker_lost is True
    assert configuration.worker_prefetch_multiplier == 1
    assert configuration.task_soft_time_limit == settings.stt_soft_time_limit_seconds
    assert configuration.task_time_limit == settings.stt_hard_time_limit_seconds
    assert (
        configuration.broker_transport_options["visibility_timeout"]
        > settings.stt_hard_time_limit_seconds
    )
    assert configuration.result_backend is None


def test_worker_master_import_does_not_import_native_model_packages() -> None:
    assert "funasr" not in sys.modules
    assert "torch" not in sys.modules
    assert "torchaudio" not in sys.modules


def test_publisher_sends_only_the_job_identifier(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_send_task(name: str, **kwargs: object) -> None:
        calls.append((name, kwargs))

    monkeypatch.setattr(celery_module.celery_app, "send_task", fake_send_task)
    publisher = celery_module.CeleryTranscriptionPublisher()
    job_id = uuid4()

    publisher.publish(job_id)

    assert calls == [
        (
            "stt.transcribe",
            {
                "args": [str(job_id)],
                "task_id": str(job_id),
                "queue": celery_module.settings.stt_queue,
            },
        )
    ]
