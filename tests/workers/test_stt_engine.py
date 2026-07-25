from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.workers import stt_engine
from inspire_flow_backend.workers.stt_engine import (
    AudioTooLongError,
    ModelUnavailableError,
)

MODEL = (
    "vaibhavs10/incredibly-fast-whisper:"
    "3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c"
)


def fake_duration(monkeypatch, seconds: float = 1.0) -> None:
    monkeypatch.setattr(stt_engine, "_audio_duration", lambda path: seconds)


def make_engine(
    handler,
    *,
    sleep=lambda seconds: None,
    monotonic=None,
    prediction_timeout_seconds: int = 540,
) -> object:
    client = httpx.Client(
        base_url="https://ai.hackclub.com/proxy/v1/replicate/",
        headers={"Authorization": "Bearer synthetic-test-key"},
        transport=httpx.MockTransport(handler),
    )
    return stt_engine.ReplicateWhisperEngine(
        client=client,
        model=MODEL,
        max_duration_seconds=300,
        prediction_timeout_seconds=prediction_timeout_seconds,
        poll_interval_seconds=1,
        sleep=sleep,
        monotonic=monotonic,
    )


def test_factory_requires_api_key() -> None:
    with pytest.raises(ModelUnavailableError):
        stt_engine.create_replicate_whisper_engine(Settings(_env_file=None, stt_enabled=True))


def test_factory_builds_hack_club_client_without_exposing_secret() -> None:
    settings = Settings(
        _env_file=None,
        stt_api_key=SecretStr("synthetic-test-key"),
    )

    engine = stt_engine.create_replicate_whisper_engine(settings)

    assert engine.device == "replicate"
    assert str(engine._client.base_url) == ("https://ai.hackclub.com/proxy/v1/replicate/")
    assert engine._client.headers["Authorization"] == "Bearer synthetic-test-key"
    assert "synthetic-test-key" not in repr(engine)


@pytest.mark.parametrize(
    ("language", "provider_language", "detected_language"),
    [
        ("auto", "None", "zh"),
        ("zh", "chinese", "zh"),
        ("yue", "cantonese", "yue"),
        ("en", "english", "en"),
        ("ja", "japanese", "ja"),
        ("ko", "korean", "ko"),
    ],
)
def test_engine_uploads_audio_and_submits_fixed_version_prediction(
    monkeypatch,
    tmp_path: Path,
    language: str,
    provider_language: str,
    detected_language: str,
) -> None:
    fake_duration(monkeypatch, 2.5)
    audio_path = tmp_path / "job.audio"
    audio_path.write_bytes(b"audio-bytes")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/files"):
            assert b"audio-bytes" in request.content
            return httpx.Response(
                201,
                json={
                    "id": "file-1",
                    "urls": {"get": "https://files.example/audio"},
                },
            )
        if request.method == "POST" and request.url.path.endswith("/predictions"):
            assert request.headers["Prefer"] == "wait=60"
            assert request.headers["Cancel-After"] == "540s"
            assert request.read()
            payload = json.loads(request.content)
            assert payload == {
                "version": MODEL,
                "input": {
                    "audio": "https://files.example/audio",
                    "task": "transcribe",
                    "language": provider_language,
                    "batch_size": 24,
                    "timestamp": "chunk",
                    "diarise_audio": False,
                },
            }
            output_language = "chinese" if language == "auto" else None
            return httpx.Response(
                201,
                json={
                    "id": "prediction-1",
                    "status": "succeeded",
                    "output": {
                        "text": "  转写正文  ",
                        "detected_language": output_language,
                        "chunks": [{"text": "ignored"}],
                    },
                },
            )
        if request.method == "DELETE" and request.url.path.endswith("/files/file-1"):
            return httpx.Response(204)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    engine = make_engine(handler)
    result = engine.transcribe(audio_path, language=language, use_itn=True)

    assert result.text == "转写正文"
    assert result.detected_language == detected_language
    assert result.duration_seconds == 2.5
    assert result.emotions == ()
    assert result.audio_events == ()
    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/proxy/v1/replicate/files"),
        ("POST", "/proxy/v1/replicate/predictions"),
        ("DELETE", "/proxy/v1/replicate/files/file-1"),
    ]


def test_engine_polls_non_terminal_prediction_without_following_provider_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_duration(monkeypatch)
    audio_path = tmp_path / "job.audio"
    audio_path.write_bytes(b"audio")
    polls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        if request.url.path.endswith("/files"):
            return httpx.Response(
                201,
                json={"id": "file-1", "urls": {"get": "https://files.example/audio"}},
            )
        if request.method == "POST" and request.url.path.endswith("/predictions"):
            return httpx.Response(
                201,
                json={
                    "id": "prediction-1",
                    "status": "starting",
                    "urls": {"get": "https://api.replicate.com/v1/predictions/bypass"},
                },
            )
        if request.method == "GET":
            assert request.url.host == "ai.hackclub.com"
            assert request.url.path.endswith("/predictions/prediction-1")
            polls += 1
            if polls == 1:
                return httpx.Response(
                    200,
                    json={"id": "prediction-1", "status": "processing"},
                )
            return httpx.Response(
                200,
                json={
                    "id": "prediction-1",
                    "status": "succeeded",
                    "output": {"text": "done"},
                },
            )
        if request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError

    engine = make_engine(handler, sleep=sleeps.append)

    result = engine.transcribe(audio_path, language="auto", use_itn=False)

    assert result.text == "done"
    assert result.detected_language is None
    assert polls == 2
    assert sleeps == [1, 1]


def test_duration_limit_is_checked_before_provider_requests(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_duration(monkeypatch, 301)
    requested = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(500)

    engine = make_engine(handler)

    with pytest.raises(AudioTooLongError):
        engine.transcribe(tmp_path / "long.audio", language="auto", use_itn=True)

    assert requested is False


def test_audio_duration_falls_back_to_ffprobe(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.webm"
    commands: list[list[str]] = []
    monkeypatch.setattr(
        stt_engine,
        "import_module",
        lambda name: SimpleNamespace(
            info=lambda path: (_ for _ in ()).throw(RuntimeError("unsupported container"))
        ),
    )

    def fake_run(command: list[str], **kwargs: object) -> object:
        commands.append(command)
        assert kwargs == {
            "capture_output": True,
            "check": False,
            "text": True,
            "timeout": 10,
        }
        return SimpleNamespace(returncode=0, stdout="4.25\n")

    monkeypatch.setattr(stt_engine.subprocess, "run", fake_run)

    assert stt_engine._audio_duration(audio_path) == 4.25
    assert commands == [
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
    ]


def test_audio_duration_rejects_invalid_soundfile_and_ffprobe_output(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        stt_engine,
        "import_module",
        lambda name: SimpleNamespace(
            info=lambda path: (_ for _ in ()).throw(RuntimeError("decode failed"))
        ),
    )
    monkeypatch.setattr(
        stt_engine.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(returncode=1, stdout="provider detail"),
    )

    with pytest.raises(stt_engine.InvalidAudioError):
        stt_engine._audio_duration(tmp_path / "invalid.webm")


@pytest.mark.parametrize(
    "prediction",
    [
        {"id": "prediction-1", "status": "failed", "error": "secret upstream detail"},
        {"id": "prediction-1", "status": "canceled"},
        {"id": "prediction-1", "status": "succeeded", "output": None},
        {"id": "prediction-1", "status": "succeeded", "output": {"text": 123}},
    ],
)
def test_provider_failures_collapse_to_safe_model_error(
    monkeypatch,
    tmp_path: Path,
    prediction: dict[str, object],
) -> None:
    fake_duration(monkeypatch)
    audio_path = tmp_path / "job.audio"
    audio_path.write_bytes(b"audio")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files"):
            return httpx.Response(
                201,
                json={"id": "file-1", "urls": {"get": "https://files.example/audio"}},
            )
        if request.method == "POST":
            return httpx.Response(201, json=prediction)
        if request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError

    with pytest.raises(ModelUnavailableError) as raised:
        make_engine(handler).transcribe(audio_path, language="auto", use_itn=True)

    assert "secret upstream detail" not in str(raised.value)


def test_polling_timeout_cancels_prediction_and_raises_safe_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_duration(monkeypatch)
    audio_path = tmp_path / "job.audio"
    audio_path.write_bytes(b"audio")
    times = iter([0.0, 0.0, 2.0])
    canceled = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal canceled
        if request.url.path.endswith("/files"):
            return httpx.Response(
                201,
                json={"id": "file-1", "urls": {"get": "https://files.example/audio"}},
            )
        if request.method == "POST" and request.url.path.endswith("/predictions"):
            return httpx.Response(
                201,
                json={"id": "prediction-1", "status": "starting"},
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"id": "prediction-1", "status": "processing"},
            )
        if request.url.path.endswith("/predictions/prediction-1/cancel"):
            canceled = True
            return httpx.Response(200, json={"status": "canceled"})
        if request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError

    engine = make_engine(
        handler,
        monotonic=lambda: next(times),
        prediction_timeout_seconds=1,
    )

    with pytest.raises(ModelUnavailableError):
        engine.transcribe(audio_path, language="auto", use_itn=True)

    assert canceled is True


def test_prediction_deadline_includes_initial_synchronous_wait(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_duration(monkeypatch)
    audio_path = tmp_path / "job.audio"
    audio_path.write_bytes(b"audio")
    clock = 0.0
    canceled = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal canceled, clock
        if request.url.path.endswith("/files"):
            return httpx.Response(
                201,
                json={"id": "file-1", "urls": {"get": "https://files.example/audio"}},
            )
        if request.method == "POST" and request.url.path.endswith("/predictions"):
            clock = 2.0
            return httpx.Response(
                201,
                json={"id": "prediction-1", "status": "starting"},
            )
        if request.url.path.endswith("/predictions/prediction-1/cancel"):
            canceled = True
            return httpx.Response(200, json={"status": "canceled"})
        if request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError("prediction should time out before polling")

    engine = make_engine(
        handler,
        monotonic=lambda: clock,
        prediction_timeout_seconds=1,
    )

    with pytest.raises(ModelUnavailableError):
        engine.transcribe(audio_path, language="auto", use_itn=True)

    assert canceled is True


def test_http_errors_are_wrapped_without_response_body(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_duration(monkeypatch)
    audio_path = tmp_path / "job.audio"
    audio_path.write_bytes(b"audio")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="synthetic-secret-provider-body")

    with pytest.raises(ModelUnavailableError) as raised:
        make_engine(handler).transcribe(audio_path, language="auto", use_itn=True)

    assert "synthetic-secret-provider-body" not in str(raised.value)
