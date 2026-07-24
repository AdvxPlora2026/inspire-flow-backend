import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session, sessionmaker

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.core.context_security import ContextCipher
from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.database import create_database_engine
from inspire_flow_backend.data.models.agent_conversation import AgentConversation
from inspire_flow_backend.data.models.agent_message import AgentMessage
from inspire_flow_backend.data.models.auth_session import AuthSession
from inspire_flow_backend.data.models.transcription_job import TranscriptionJob
from inspire_flow_backend.data.models.user import User
from inspire_flow_backend.data.models.user_memory import UserMemory
from inspire_flow_backend.data.models.user_profile import UserProfile
from inspire_flow_backend.workers import stt_tasks
from inspire_flow_backend.workers.stt_engine import (
    AudioTooLongError,
    TranscriptionResult,
)
from inspire_flow_backend.workers.stt_tasks import run_transcription_job


def test_isolated_worker_import_registers_orm_models() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from sqlalchemy.orm import configure_mappers;"
                "import inspire_flow_backend.workers.stt_tasks;"
                "configure_mappers()"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    assert {
        AgentConversation.__tablename__,
        AgentMessage.__tablename__,
        AuthSession.__tablename__,
        TranscriptionJob.__tablename__,
        User.__tablename__,
        UserMemory.__tablename__,
        UserProfile.__tablename__,
    } <= set(Base.metadata.tables)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def make_job(
    factory: sessionmaker[Session],
    *,
    attempt_count: int = 0,
) -> TranscriptionJob:
    now = utc_now()
    user = User(
        nickname="aria",
        nickname_key=f"aria-{uuid4()}",
        password_hash="test-only-hash",
        created_at=now,
        updated_at=now,
    )
    job = TranscriptionJob(
        id=uuid4(),
        user=user,
        status="queued",
        language="zh",
        use_itn=True,
        attempt_count=attempt_count,
        created_at=now,
        updated_at=now,
    )
    with factory() as db:
        db.add(job)
        db.commit()
        db.refresh(job)
    return job


class SuccessfulEngine:
    device = "cpu"

    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio_path: Path, *, language: str, use_itn: bool):
        self.calls += 1
        assert audio_path.read_bytes() == b"audio"
        assert language == "zh"
        assert use_itn is True
        return TranscriptionResult(
            text="转写后的正文",
            detected_language="zh",
            duration_seconds=2.5,
            emotions=("happy", "neutral"),
            audio_events=("speech", "laughter"),
        )


class TooLongEngine:
    device = "cpu"

    def transcribe(self, audio_path: Path, *, language: str, use_itn: bool):
        del audio_path, language, use_itn
        raise AudioTooLongError


def test_engine_is_loaded_once_and_only_then_reports_readiness(monkeypatch) -> None:
    engine = SuccessfulEngine()
    readiness_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(stt_tasks, "_engine", None)
    monkeypatch.setattr(stt_tasks, "_readiness_heartbeat", None)
    monkeypatch.setattr(stt_tasks, "create_sensevoice_engine", lambda settings: engine)
    monkeypatch.setattr(
        stt_tasks,
        "start_readiness_heartbeat",
        lambda settings, device: readiness_calls.append((settings.stt_queue, device)),
    )

    first = stt_tasks.get_engine()
    second = stt_tasks.get_engine()

    assert first is engine
    assert second is engine
    assert readiness_calls == [("stt", "cpu")]


def test_worker_ready_enqueues_model_warmup(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_send_task(name: str, **kwargs: object) -> None:
        calls.append((name, kwargs))

    monkeypatch.setattr(stt_tasks.celery_app, "send_task", fake_send_task)

    stt_tasks.enqueue_warmup()

    assert calls == [
        (
            "stt.warmup",
            {"queue": stt_tasks.get_settings().stt_queue},
        )
    ]


def test_task_encrypts_success_and_is_idempotent(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    settings = Settings(_env_file=None, stt_enabled=True, stt_spool_dir=tmp_path / "spool")
    cipher = ContextCipher(Fernet.generate_key())
    job = make_job(session_factory)
    spool_path = settings.stt_spool_dir / f"{job.id}.audio"
    spool_path.parent.mkdir()
    spool_path.write_bytes(b"audio")
    engine = SuccessfulEngine()

    run_transcription_job(
        job.id,
        session_factory=session_factory,
        settings=settings,
        cipher=cipher,
        engine=engine,
    )
    run_transcription_job(
        job.id,
        session_factory=session_factory,
        settings=settings,
        cipher=cipher,
        engine=engine,
    )

    with session_factory() as db:
        persisted = db.get(TranscriptionJob, job.id)
        assert persisted is not None
        assert persisted.status == "succeeded"
        assert persisted.attempt_count == 1
        assert persisted.transcript_ciphertext is not None
        assert "转写后的正文" not in persisted.transcript_ciphertext
        assert cipher.decrypt_text(persisted.transcript_ciphertext) == "转写后的正文"
        assert persisted.analysis_ciphertext is not None
        assert "happy" not in persisted.analysis_ciphertext
        assert cipher.decrypt_json(persisted.analysis_ciphertext) == {
            "audio_events": ["speech", "laughter"],
            "emotions": ["happy", "neutral"],
            "version": 1,
        }
        assert persisted.detected_language == "zh"
        assert persisted.duration_seconds == 2.5
    assert engine.calls == 1
    assert not spool_path.exists()


def test_known_audio_failure_is_safe_and_removes_staged_audio(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    settings = Settings(_env_file=None, stt_enabled=True, stt_spool_dir=tmp_path / "spool")
    job = make_job(session_factory)
    spool_path = settings.stt_spool_dir / f"{job.id}.audio"
    spool_path.parent.mkdir()
    spool_path.write_bytes(b"audio")

    run_transcription_job(
        job.id,
        session_factory=session_factory,
        settings=settings,
        cipher=ContextCipher(Fernet.generate_key()),
        engine=TooLongEngine(),
    )

    with session_factory() as db:
        persisted = db.get(TranscriptionJob, job.id)
        assert persisted is not None
        assert persisted.status == "failed"
        assert persisted.error_code == "audio_too_long"
        assert persisted.transcript_ciphertext is None
    assert not spool_path.exists()


def test_attempt_limit_finishes_without_calling_engine(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        stt_enabled=True,
        stt_spool_dir=tmp_path / "spool",
        stt_max_attempts=3,
    )
    job = make_job(session_factory, attempt_count=3)
    spool_path = settings.stt_spool_dir / f"{job.id}.audio"
    spool_path.parent.mkdir()
    spool_path.write_bytes(b"audio")
    engine = SuccessfulEngine()

    run_transcription_job(
        job.id,
        session_factory=session_factory,
        settings=settings,
        cipher=ContextCipher(Fernet.generate_key()),
        engine=engine,
    )

    with session_factory() as db:
        persisted = db.get(TranscriptionJob, job.id)
        assert persisted is not None
        assert persisted.status == "failed"
        assert persisted.error_code == "stt_worker_lost"
        assert persisted.attempt_count == 3
    assert engine.calls == 0
    assert not spool_path.exists()
