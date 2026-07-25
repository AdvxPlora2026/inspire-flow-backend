from __future__ import annotations

import math
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

import httpx

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.schemas.transcriptions import (
    TranscriptionAudioEvent,
    TranscriptionEmotion,
    TranscriptionLanguage,
)

_PROVIDER_LANGUAGES: dict[TranscriptionLanguage, str] = {
    "auto": "None",
    "zh": "chinese",
    "yue": "cantonese",
    "en": "english",
    "ja": "japanese",
    "ko": "korean",
}
_PUBLIC_LANGUAGES = {value: key for key, value in _PROVIDER_LANGUAGES.items() if key != "auto"}
_ACTIVE_PREDICTION_STATES = {"starting", "processing"}
_TERMINAL_PREDICTION_STATES = {"succeeded", "failed", "canceled"}


class AudioTooLongError(RuntimeError):
    pass


class InvalidAudioError(RuntimeError):
    pass


class ModelUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    detected_language: str | None
    duration_seconds: float
    emotions: tuple[TranscriptionEmotion, ...] = ()
    audio_events: tuple[TranscriptionAudioEvent, ...] = ()


class SttEngine(Protocol):
    device: str

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: TranscriptionLanguage,
        use_itn: bool,
    ) -> TranscriptionResult: ...


class ReplicateWhisperEngine:
    device = "replicate"

    def __init__(
        self,
        *,
        client: httpx.Client,
        model: str,
        max_duration_seconds: int,
        prediction_timeout_seconds: int,
        poll_interval_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._max_duration_seconds = max_duration_seconds
        self._prediction_timeout_seconds = prediction_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic or time.monotonic

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: TranscriptionLanguage,
        use_itn: bool,
    ) -> TranscriptionResult:
        del use_itn
        duration = _audio_duration(audio_path)
        if duration > self._max_duration_seconds:
            raise AudioTooLongError

        remote_file_id: str | None = None
        try:
            remote_file_id, audio_url = self._upload_audio(audio_path)
            prediction_deadline = self._monotonic() + self._prediction_timeout_seconds
            prediction = self._create_prediction(audio_url, language=language)
            prediction = self._wait_for_prediction(
                prediction,
                deadline=prediction_deadline,
            )
            return self._build_result(
                prediction,
                requested_language=language,
                duration_seconds=duration,
            )
        except ModelUnavailableError:
            raise
        except Exception as exc:
            raise ModelUnavailableError from exc
        finally:
            if remote_file_id is not None:
                self._delete_remote_file(remote_file_id)

    def _upload_audio(self, audio_path: Path) -> tuple[str, str]:
        with audio_path.open("rb") as audio_file:
            response = self._client.post(
                "files",
                files={
                    "content": (
                        "audio",
                        audio_file,
                        "application/octet-stream",
                    )
                },
            )
        payload = _response_json(response)
        remote_file_id = payload.get("id")
        urls = payload.get("urls")
        if not isinstance(remote_file_id, str) or not remote_file_id:
            raise ModelUnavailableError
        if not isinstance(urls, dict):
            raise ModelUnavailableError
        audio_url = urls.get("get")
        if not isinstance(audio_url, str) or not audio_url.startswith("https://"):
            raise ModelUnavailableError
        return remote_file_id, audio_url

    def _create_prediction(
        self,
        audio_url: str,
        *,
        language: TranscriptionLanguage,
    ) -> dict[str, Any]:
        response = self._client.post(
            "predictions",
            headers={
                "Prefer": "wait=60",
                "Cancel-After": f"{self._prediction_timeout_seconds}s",
            },
            json={
                "version": self._model,
                "input": {
                    "audio": audio_url,
                    "task": "transcribe",
                    "language": _PROVIDER_LANGUAGES[language],
                    "batch_size": 24,
                    "timestamp": "chunk",
                    "diarise_audio": False,
                },
            },
        )
        return _response_json(response)

    def _wait_for_prediction(
        self,
        prediction: dict[str, Any],
        *,
        deadline: float,
    ) -> dict[str, Any]:
        prediction_id = prediction.get("id")
        status = prediction.get("status")
        if not isinstance(prediction_id, str) or not prediction_id:
            raise ModelUnavailableError
        if status in _TERMINAL_PREDICTION_STATES:
            return prediction
        if status not in _ACTIVE_PREDICTION_STATES:
            raise ModelUnavailableError

        while status in _ACTIVE_PREDICTION_STATES:
            if self._monotonic() >= deadline:
                self._cancel_prediction(prediction_id)
                raise ModelUnavailableError
            self._sleep(self._poll_interval_seconds)
            response = self._client.get(f"predictions/{prediction_id}")
            prediction = _response_json(response)
            status = prediction.get("status")
            if status not in _ACTIVE_PREDICTION_STATES | _TERMINAL_PREDICTION_STATES:
                raise ModelUnavailableError
        return prediction

    def _build_result(
        self,
        prediction: dict[str, Any],
        *,
        requested_language: TranscriptionLanguage,
        duration_seconds: float,
    ) -> TranscriptionResult:
        if prediction.get("status") != "succeeded":
            raise ModelUnavailableError
        output = prediction.get("output")
        if not isinstance(output, dict):
            raise ModelUnavailableError
        text = output.get("text")
        if not isinstance(text, str):
            raise ModelUnavailableError

        provider_language = output.get("detected_language") or output.get("language")
        detected_language = _normalize_detected_language(provider_language)
        if detected_language is None and requested_language != "auto":
            detected_language = requested_language
        return TranscriptionResult(
            text=text.strip(),
            detected_language=detected_language,
            duration_seconds=duration_seconds,
        )

    def _cancel_prediction(self, prediction_id: str) -> None:
        try:
            response = self._client.post(f"predictions/{prediction_id}/cancel")
            response.raise_for_status()
        except Exception:
            return

    def _delete_remote_file(self, remote_file_id: str) -> None:
        try:
            response = self._client.delete(f"files/{remote_file_id}")
            response.raise_for_status()
        except Exception:
            return


def create_replicate_whisper_engine(settings: Settings) -> ReplicateWhisperEngine:
    if settings.stt_api_key is None:
        raise ModelUnavailableError
    api_key = settings.stt_api_key.get_secret_value()
    if not api_key:
        raise ModelUnavailableError

    client = httpx.Client(
        base_url=f"{str(settings.stt_base_url).rstrip('/')}/",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=settings.stt_request_timeout_seconds,
    )
    return ReplicateWhisperEngine(
        client=client,
        model=settings.stt_model,
        max_duration_seconds=settings.stt_max_duration_seconds,
        prediction_timeout_seconds=settings.stt_prediction_timeout_seconds,
        poll_interval_seconds=settings.stt_poll_interval_seconds,
    )


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise ModelUnavailableError from exc
    if not isinstance(payload, dict):
        raise ModelUnavailableError
    return payload


def _normalize_detected_language(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in _PUBLIC_LANGUAGES:
        return _PUBLIC_LANGUAGES[normalized]
    if normalized in _PROVIDER_LANGUAGES and normalized != "auto":
        return normalized
    return None


def _audio_duration(audio_path: Path) -> float:
    try:
        soundfile = import_module("soundfile")
        metadata = soundfile.info(str(audio_path))
        frames = int(metadata.frames)
        sample_rate = int(metadata.samplerate)
        if frames < 0 or sample_rate <= 0:
            raise ValueError
        return frames / sample_rate
    except Exception:
        pass

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise ValueError
        duration = float(result.stdout.strip())
        if duration < 0 or not math.isfinite(duration):
            raise ValueError
        return duration
    except Exception as exc:
        raise InvalidAudioError from exc
