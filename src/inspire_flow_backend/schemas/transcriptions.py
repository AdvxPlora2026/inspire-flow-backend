from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

TranscriptionLanguage = Literal["auto", "zh", "yue", "en", "ja", "ko"]
TranscriptionStatus = Literal["queued", "running", "succeeded", "failed"]


class TranscriptionFailurePublic(BaseModel):
    code: str
    message: str


class TranscriptionJobPublic(BaseModel):
    id: UUID
    status: TranscriptionStatus
    language: TranscriptionLanguage
    use_itn: bool
    text: str | None
    detected_language: str | None
    duration_seconds: float | None
    error: TranscriptionFailurePublic | None
    attempt_count: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
