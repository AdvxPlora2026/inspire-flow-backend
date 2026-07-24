import os
import re
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol

from inspire_flow_backend.core.config import Settings
from inspire_flow_backend.schemas.transcriptions import (
    TranscriptionAudioEvent,
    TranscriptionEmotion,
    TranscriptionLanguage,
)

_SENSEVOICE_TOKEN = re.compile(r"<\|([^<>]*?)\|>")
_LANGUAGES = {"en", "ja", "ko", "nospeech", "yue", "zh"}
_EMOTIONS: dict[str, TranscriptionEmotion] = {
    "ANGRY": "angry",
    "DISGUSTED": "disgusted",
    "FEARFUL": "fearful",
    "HAPPY": "happy",
    "NEUTRAL": "neutral",
    "SAD": "sad",
    "SURPRISED": "surprised",
}
_AUDIO_EVENTS: dict[str, TranscriptionAudioEvent] = {
    "Applause": "applause",
    "BGM": "bgm",
    "Breath": "breath",
    "Cough": "cough",
    "Cry": "cry",
    "Laughter": "laughter",
    "Sing": "sing",
    "Sneeze": "sneeze",
    "Speech": "speech",
    "Speech_Noise": "speech_noise",
}


class DeviceUnavailableError(RuntimeError):
    pass


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


@dataclass(frozen=True, slots=True)
class ParsedSenseVoiceOutput:
    text: str
    detected_language: str | None
    emotions: tuple[TranscriptionEmotion, ...]
    audio_events: tuple[TranscriptionAudioEvent, ...]


def parse_sensevoice_output(raw_text: str) -> ParsedSenseVoiceOutput:
    detected_language = None
    emotions: list[TranscriptionEmotion] = []
    audio_events: list[TranscriptionAudioEvent] = []

    for match in _SENSEVOICE_TOKEN.finditer(raw_text):
        token = match.group(1)
        if detected_language is None and token in _LANGUAGES:
            detected_language = token
        emotion = _EMOTIONS.get(token)
        if emotion is not None and emotion not in emotions:
            emotions.append(emotion)
        audio_event = _AUDIO_EVENTS.get(token)
        if audio_event is not None and audio_event not in audio_events:
            audio_events.append(audio_event)

    text = _SENSEVOICE_TOKEN.sub("", raw_text).strip()
    text = re.sub(r"[ \t]+", " ", text)
    return ParsedSenseVoiceOutput(
        text=text,
        detected_language=detected_language,
        emotions=tuple(emotions),
        audio_events=tuple(audio_events),
    )


class SttEngine(Protocol):
    device: str

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: TranscriptionLanguage,
        use_itn: bool,
    ) -> TranscriptionResult: ...


def choose_device(
    requested: str,
    *,
    cuda_available: bool,
    mps_available: bool,
) -> str:
    if requested == "auto":
        if cuda_available:
            return "cuda"
        if mps_available:
            return "mps"
        return "cpu"
    if requested == "cuda" and not cuda_available:
        raise DeviceUnavailableError("CUDA is not available")
    if requested == "mps" and not mps_available:
        raise DeviceUnavailableError("MPS is not available")
    if requested in {"cpu", "cuda", "mps"}:
        return requested
    raise DeviceUnavailableError("Unknown STT device")


class SenseVoiceEngine:
    def __init__(
        self,
        *,
        model: object,
        device: str,
        max_duration_seconds: int,
        cpu_model_factory=None,
    ) -> None:
        self._model = model
        self.device = device
        self._max_duration_seconds = max_duration_seconds
        self._cpu_model_factory = cpu_model_factory

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: TranscriptionLanguage,
        use_itn: bool,
    ) -> TranscriptionResult:
        duration = _audio_duration(audio_path)
        if duration > self._max_duration_seconds:
            raise AudioTooLongError
        try:
            result = self._generate(audio_path, language=language, use_itn=use_itn)
        except Exception as exc:
            if self._cpu_model_factory is None:
                raise ModelUnavailableError from exc
            self._model = self._cpu_model_factory()
            self._cpu_model_factory = None
            self.device = "cpu"
            try:
                result = self._generate(audio_path, language=language, use_itn=use_itn)
            except Exception as fallback_exc:
                raise ModelUnavailableError from fallback_exc

        if not isinstance(result, list) or not result or not isinstance(result[0], dict):
            raise ModelUnavailableError
        raw_text = result[0].get("text")
        if not isinstance(raw_text, str):
            raise ModelUnavailableError
        parsed = parse_sensevoice_output(raw_text)
        detected_language = result[0].get("language") or parsed.detected_language
        return TranscriptionResult(
            text=parsed.text,
            detected_language=(str(detected_language) if detected_language is not None else None),
            duration_seconds=duration,
            emotions=parsed.emotions,
            audio_events=parsed.audio_events,
        )

    def _generate(
        self,
        audio_path: Path,
        *,
        language: TranscriptionLanguage,
        use_itn: bool,
    ):
        return self._model.generate(
            input=str(audio_path),
            cache={},
            language=language,
            use_itn=use_itn,
            batch_size_s=60,
            merge_vad=True,
            merge_length_s=15,
        )


def create_sensevoice_engine(settings: Settings) -> SenseVoiceEngine:
    torch = import_module("torch")
    cuda_available = bool(torch.cuda.is_available())
    mps_available = bool(torch.backends.mps.is_available())
    device = choose_device(
        settings.stt_device,
        cuda_available=cuda_available,
        mps_available=mps_available,
    )

    os.environ.setdefault("HF_HOME", str(settings.stt_model_cache_dir))
    os.environ.setdefault("MODELSCOPE_CACHE", str(settings.stt_model_cache_dir))
    os.environ["HF_HUB_DISABLE_XET"] = "1" if settings.stt_hf_disable_xet else "0"
    funasr = import_module("funasr")
    auto_model = funasr.AutoModel

    def build_model(target_device: str):
        return auto_model(
            model=settings.stt_model,
            hub=settings.stt_model_hub,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 30_000},
            device=target_device,
            disable_update=True,
        )

    cpu_model_factory = None
    try:
        model = build_model(device)
    except Exception as exc:
        if settings.stt_device != "auto" or device == "cpu":
            raise ModelUnavailableError from exc
        device = "cpu"
        try:
            model = build_model(device)
        except Exception as fallback_exc:
            raise ModelUnavailableError from fallback_exc
    else:
        if settings.stt_device == "auto" and device != "cpu":

            def build_cpu_model():
                return build_model("cpu")

            cpu_model_factory = build_cpu_model

    return SenseVoiceEngine(
        model=model,
        device=device,
        max_duration_seconds=settings.stt_max_duration_seconds,
        cpu_model_factory=cpu_model_factory,
    )


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
        try:
            librosa = import_module("librosa")
            duration = float(librosa.get_duration(path=str(audio_path)))
            if duration < 0:
                raise ValueError
            return duration
        except Exception as exc:
            raise InvalidAudioError from exc
