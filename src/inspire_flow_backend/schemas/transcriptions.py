from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

TranscriptionLanguage = Literal["auto", "zh", "yue", "en", "ja", "ko"]
TranscriptionStatus = Literal["queued", "running", "succeeded", "failed"]
TranscriptionEmotion = Literal[
    "neutral",
    "happy",
    "sad",
    "angry",
    "fearful",
    "disgusted",
    "surprised",
]
TranscriptionAudioEvent = Literal[
    "speech",
    "bgm",
    "applause",
    "laughter",
    "cry",
    "sneeze",
    "breath",
    "cough",
    "sing",
    "speech_noise",
]


class TranscriptionFailurePublic(BaseModel):
    code: str
    message: str


class TranscriptionAnalysisStored(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    emotions: list[TranscriptionEmotion]
    audio_events: list[TranscriptionAudioEvent]


class TranscriptionJobPublic(BaseModel):
    id: UUID
    status: TranscriptionStatus
    language: TranscriptionLanguage
    use_itn: bool
    text: str | None
    detected_language: str | None
    emotions: list[TranscriptionEmotion] | None
    audio_events: list[TranscriptionAudioEvent] | None
    duration_seconds: float | None
    error: TranscriptionFailurePublic | None
    attempt_count: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
