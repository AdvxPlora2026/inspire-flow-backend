from json import loads

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.workers.readiness import (
    read_stt_readiness,
    readiness_key,
    write_stt_readiness,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.expirations[key] = ex

    def get(self, key: str) -> str | None:
        return self.values.get(key)


def test_readiness_is_false_until_model_child_reports_success() -> None:
    settings = Settings(_env_file=None, stt_queue="creator-stt", stt_ready_ttl_seconds=30)
    redis = FakeRedis()

    missing = read_stt_readiness(redis, settings)
    write_stt_readiness(redis, settings, device="mps", process_id=42)
    ready = read_stt_readiness(redis, settings)

    assert readiness_key(settings) == "inspireflow:stt:creator-stt:ready"
    assert missing.ready is False
    assert ready.ready is True
    assert ready.device == "mps"
    assert ready.process_id == 42
    assert redis.expirations[readiness_key(settings)] == 30
    payload = loads(redis.values[readiness_key(settings)])
    assert set(payload) == {"device", "process_id", "reported_at"}


def test_malformed_readiness_payload_is_treated_as_not_ready() -> None:
    settings = Settings(_env_file=None)
    redis = FakeRedis()
    redis.values[readiness_key(settings)] = "not-json"

    readiness = read_stt_readiness(redis, settings)

    assert readiness.ready is False
