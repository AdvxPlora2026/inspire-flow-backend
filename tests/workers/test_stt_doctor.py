from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.workers.readiness import write_stt_readiness
from inspire_flow_backend.workers.stt_doctor import build_doctor_report


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, key: str, value: str, *, ex: int) -> None:
        del ex
        self.values[key] = value

    def get(self, key: str) -> str | None:
        return self.values.get(key)


def test_doctor_distinguishes_worker_liveness_from_model_readiness() -> None:
    settings = Settings(_env_file=None, stt_enabled=True)
    redis = FakeRedis()

    warming = build_doctor_report(
        settings,
        broker_ping=lambda: True,
        worker_ping=lambda: True,
        readiness_client=redis,
    )
    write_stt_readiness(redis, settings, device="replicate", process_id=73)
    ready = build_doctor_report(
        settings,
        broker_ping=lambda: True,
        worker_ping=lambda: True,
        readiness_client=redis,
    )

    assert warming.status == "warming"
    assert warming.broker == "ok"
    assert warming.worker == "ok"
    assert warming.model == "not_ready"
    assert ready.status == "ready"
    assert ready.model == "ready"
    assert ready.device == "replicate"
    assert ready.process_id == 73


def test_doctor_reports_disabled_and_unavailable_without_raising() -> None:
    redis = FakeRedis()

    disabled = build_doctor_report(
        Settings(_env_file=None, stt_enabled=False),
        broker_ping=lambda: True,
        worker_ping=lambda: True,
        readiness_client=redis,
    )
    unavailable = build_doctor_report(
        Settings(_env_file=None, stt_enabled=True),
        broker_ping=lambda: (_ for _ in ()).throw(ConnectionError("secret broker")),
        worker_ping=lambda: True,
        readiness_client=redis,
    )

    assert disabled.status == "disabled"
    assert unavailable.status == "unavailable"
    assert unavailable.broker == "unavailable"
