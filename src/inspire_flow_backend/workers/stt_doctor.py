import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

from inspire_flow_backend.core.config import Settings, get_settings
from inspire_flow_backend.workers.readiness import (
    RedisReadinessClient,
    read_stt_readiness,
)


@dataclass(frozen=True, slots=True)
class SttDoctorReport:
    status: Literal["disabled", "unavailable", "warming", "ready"]
    broker: Literal["not_checked", "ok", "unavailable"]
    worker: Literal["not_checked", "ok", "unavailable"]
    model: Literal["not_checked", "not_ready", "ready"]
    device: str | None = None
    process_id: int | None = None


def build_doctor_report(
    settings: Settings,
    *,
    broker_ping: Callable[[], bool],
    worker_ping: Callable[[], bool],
    readiness_client: RedisReadinessClient,
) -> SttDoctorReport:
    if not settings.stt_enabled:
        return SttDoctorReport(
            status="disabled",
            broker="not_checked",
            worker="not_checked",
            model="not_checked",
        )
    try:
        if not broker_ping():
            raise ConnectionError
    except Exception:
        return SttDoctorReport(
            status="unavailable",
            broker="unavailable",
            worker="not_checked",
            model="not_checked",
        )
    try:
        if not worker_ping():
            raise ConnectionError
    except Exception:
        return SttDoctorReport(
            status="unavailable",
            broker="ok",
            worker="unavailable",
            model="not_checked",
        )
    try:
        readiness = read_stt_readiness(readiness_client, settings)
    except Exception:
        readiness = None
    if readiness is None or not readiness.ready:
        return SttDoctorReport(
            status="warming",
            broker="ok",
            worker="ok",
            model="not_ready",
        )
    return SttDoctorReport(
        status="ready",
        broker="ok",
        worker="ok",
        model="ready",
        device=readiness.device,
        process_id=readiness.process_id,
    )


def main() -> int:
    from redis import Redis

    from inspire_flow_backend.workers.celery_app import celery_app

    settings = get_settings()
    redis_client = Redis.from_url(
        settings.stt_broker_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )

    def worker_ping() -> bool:
        replies = celery_app.control.inspect(timeout=1).ping()
        return bool(replies)

    report = build_doctor_report(
        settings,
        broker_ping=lambda: bool(redis_client.ping()),
        worker_ping=worker_ping,
        readiness_client=redis_client,
    )
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
    return 0 if report.status in {"disabled", "ready"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
