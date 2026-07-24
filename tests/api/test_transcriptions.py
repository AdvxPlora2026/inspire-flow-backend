from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.config import Settings, get_settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.data.models.transcription_job import TranscriptionJob

PASSWORD = "correct horse battery staple"


class FakeTranscriptionPublisher:
    def __init__(self) -> None:
        self.job_ids: list[UUID] = []

    def publish(self, job_id: UUID) -> None:
        self.job_ids.append(job_id)


class FailingTranscriptionPublisher:
    def publish(self, job_id: UUID) -> None:
        del job_id
        raise RuntimeError("private redis endpoint")


def register_and_login(client: TestClient, nickname: str) -> str:
    assert (
        client.post(
            "/api/v1/users",
            json={"nickname": nickname, "password": PASSWORD},
        ).status_code
        == 201
    )
    response = client.post(
        "/api/v1/sessions",
        json={"nickname": nickname, "password": PASSWORD},
    )
    assert response.status_code == 201
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def enable_stt(
    client: TestClient,
    spool_dir: Path,
    publisher: object,
    **overrides: object,
) -> None:
    settings = Settings(
        _env_file=None,
        stt_enabled=True,
        stt_spool_dir=spool_dir,
        **overrides,
    )
    client.app.dependency_overrides[get_settings] = lambda: settings
    client.app.state.transcription_publisher = publisher


def submit_audio(client: TestClient, token: str):
    return client.post(
        "/api/v1/transcriptions",
        headers=bearer(token),
        files={"file": ("voice.wav", b"RIFF-test-audio", "audio/wav")},
        data={"language": "zh", "use_itn": "true"},
    )


def test_submits_audio_as_an_authenticated_async_job(
    client: TestClient,
    tmp_path: Path,
) -> None:
    publisher = FakeTranscriptionPublisher()
    enable_stt(client, tmp_path / "spool", publisher)
    token = register_and_login(client, "aria")

    response = submit_audio(client, token)

    assert response.status_code == 202
    body = response.json()
    job_id = UUID(body["id"])
    assert body["status"] == "queued"
    assert body["language"] == "zh"
    assert body["use_itn"] is True
    assert body["text"] is None
    assert body["emotions"] is None
    assert body["audio_events"] is None
    assert response.headers["location"] == f"/api/v1/transcriptions/{job_id}"
    assert publisher.job_ids == [job_id]
    assert (tmp_path / "spool" / f"{job_id}.audio").read_bytes() == b"RIFF-test-audio"


def test_reads_encrypted_result_and_hides_foreign_job(
    client: TestClient,
    tmp_path: Path,
    db_session_factory: sessionmaker[Session],
    context_cipher: ContextCipher,
) -> None:
    publisher = FakeTranscriptionPublisher()
    enable_stt(client, tmp_path / "spool", publisher)
    owner_token = register_and_login(client, "aria")
    foreign_token = register_and_login(client, "beta")
    created = submit_audio(client, owner_token)
    assert created.status_code == 202
    job_id = UUID(created.json()["id"])

    with db_session_factory() as db:
        job = db.get(TranscriptionJob, job_id)
        assert job is not None
        job.status = "succeeded"
        job.transcript_ciphertext = context_cipher.encrypt_text("这是转写正文")
        job.analysis_ciphertext = context_cipher.encrypt_json(
            {
                "version": 1,
                "emotions": ["happy", "neutral"],
                "audio_events": ["speech", "laughter"],
            }
        )
        db.commit()
        raw_ciphertext = job.transcript_ciphertext
        raw_analysis_ciphertext = job.analysis_ciphertext

    owner = client.get(
        f"/api/v1/transcriptions/{job_id}",
        headers=bearer(owner_token),
    )
    foreign = client.get(
        f"/api/v1/transcriptions/{job_id}",
        headers=bearer(foreign_token),
    )

    assert owner.status_code == 200
    assert owner.json()["text"] == "这是转写正文"
    assert owner.json()["emotions"] == ["happy", "neutral"]
    assert owner.json()["audio_events"] == ["speech", "laughter"]
    assert raw_ciphertext is not None
    assert "这是转写正文" not in raw_ciphertext
    assert raw_analysis_ciphertext is not None
    assert "happy" not in raw_analysis_ciphertext
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "transcription_not_found"


def test_existing_success_without_analysis_returns_null_metadata(
    client: TestClient,
    tmp_path: Path,
    db_session_factory: sessionmaker[Session],
    context_cipher: ContextCipher,
) -> None:
    enable_stt(client, tmp_path / "spool", FakeTranscriptionPublisher())
    token = register_and_login(client, "aria")
    created = submit_audio(client, token)
    job_id = UUID(created.json()["id"])
    with db_session_factory() as db:
        job = db.get(TranscriptionJob, job_id)
        assert job is not None
        job.status = "succeeded"
        job.transcript_ciphertext = context_cipher.encrypt_text("旧结果")
        db.commit()

    response = client.get(
        f"/api/v1/transcriptions/{job_id}",
        headers=bearer(token),
    )

    assert response.status_code == 200
    assert response.json()["text"] == "旧结果"
    assert response.json()["emotions"] is None
    assert response.json()["audio_events"] is None


def test_rejects_unauthenticated_and_unsupported_audio(
    client: TestClient,
    tmp_path: Path,
) -> None:
    enable_stt(client, tmp_path / "spool", FakeTranscriptionPublisher())
    token = register_and_login(client, "aria")

    unauthenticated = client.post(
        "/api/v1/transcriptions",
        files={"file": ("voice.wav", b"audio", "audio/wav")},
    )
    unsupported = client.post(
        "/api/v1/transcriptions",
        headers=bearer(token),
        files={"file": ("payload.exe", b"not-audio", "application/octet-stream")},
    )

    assert unauthenticated.status_code == 401
    assert unsupported.status_code == 415
    assert unsupported.json()["error"]["code"] == "unsupported_audio_type"


def test_upload_limit_removes_partial_file(
    client: TestClient,
    tmp_path: Path,
) -> None:
    spool_dir = tmp_path / "spool"
    enable_stt(
        client,
        spool_dir,
        FakeTranscriptionPublisher(),
        stt_max_upload_mib=1,
    )
    token = register_and_login(client, "aria")

    response = client.post(
        "/api/v1/transcriptions",
        headers=bearer(token),
        files={"file": ("large.wav", b"x" * (1024 * 1024 + 1), "audio/wav")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "audio_too_large"
    assert not spool_dir.exists() or list(spool_dir.iterdir()) == []


def test_broker_failure_compensates_job_and_audio_without_leaking_details(
    client: TestClient,
    tmp_path: Path,
    db_session_factory: sessionmaker[Session],
) -> None:
    spool_dir = tmp_path / "spool"
    enable_stt(client, spool_dir, FailingTranscriptionPublisher())
    token = register_and_login(client, "aria")

    response = submit_audio(client, token)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "stt_unavailable"
    assert "private redis endpoint" not in response.text
    with db_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(TranscriptionJob)) == 0
    assert not spool_dir.exists() or list(spool_dir.iterdir()) == []
