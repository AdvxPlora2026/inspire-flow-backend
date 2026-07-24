import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from inspire_flow_backend.core.config import Settings


class RedisReadinessClient(Protocol):
    def set(self, key: str, value: str, *, ex: int) -> object: ...

    def get(self, key: str) -> str | bytes | None: ...


@dataclass(frozen=True, slots=True)
class SttReadiness:
    ready: bool
    device: str | None = None
    process_id: int | None = None
    reported_at: str | None = None


def readiness_key(settings: Settings) -> str:
    return f"inspireflow:stt:{settings.stt_queue}:ready"


def write_stt_readiness(
    redis: RedisReadinessClient,
    settings: Settings,
    *,
    device: str,
    process_id: int,
) -> None:
    payload = json.dumps(
        {
            "device": device,
            "process_id": process_id,
            "reported_at": datetime.now(UTC).isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    redis.set(
        readiness_key(settings),
        payload,
        ex=settings.stt_ready_ttl_seconds,
    )


def read_stt_readiness(
    redis: RedisReadinessClient,
    settings: Settings,
) -> SttReadiness:
    try:
        raw_payload = redis.get(readiness_key(settings))
        if raw_payload is None:
            return SttReadiness(ready=False)
        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode("utf-8")
        payload = json.loads(raw_payload)
        device = payload["device"]
        process_id = payload["process_id"]
        reported_at = payload["reported_at"]
        if not isinstance(device, str) or not isinstance(process_id, int):
            raise ValueError
        if not isinstance(reported_at, str):
            raise ValueError
        return SttReadiness(
            ready=True,
            device=device,
            process_id=process_id,
            reported_at=reported_at,
        )
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return SttReadiness(ready=False)


class ReadinessHeartbeat:
    def __init__(
        self,
        redis: RedisReadinessClient,
        settings: Settings,
        *,
        device: str,
    ) -> None:
        self._redis = redis
        self._settings = settings
        self._device = device
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="stt-readiness-heartbeat",
            daemon=True,
        )

    def start(self) -> None:
        self._write_safely()
        self._thread.start()

    def _run(self) -> None:
        interval = max(1.0, self._settings.stt_ready_ttl_seconds / 3)
        while not self._stop.wait(interval):
            self._write_safely()

    def _write_safely(self) -> None:
        try:
            write_stt_readiness(
                self._redis,
                self._settings,
                device=self._device,
                process_id=os.getpid(),
            )
        except Exception:
            return


def start_readiness_heartbeat(
    settings: Settings,
    device: str,
) -> ReadinessHeartbeat:
    from redis import Redis

    client = Redis.from_url(
        settings.stt_broker_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    heartbeat = ReadinessHeartbeat(client, settings, device=device)
    heartbeat.start()
    return heartbeat
