from datetime import datetime
from typing import Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UserProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bio: str | None = Field(default=None, max_length=1000)
    timezone: str | None = Field(default=None, max_length=64)
    preferred_language: str | None = Field(default=None, max_length=35)
    creator_identity: str | None = Field(default=None, max_length=100)
    content_focus: list[str] | None = Field(default=None, max_length=20)
    collaboration_preferences: str | None = Field(default=None, max_length=2000)

    @field_validator("bio", "collaboration_preferences")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("preferred_language", "creator_identity")
    @classmethod
    def normalize_nonblank_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Timezone cannot be blank")
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Timezone must be a valid IANA zone") from exc
        return normalized

    @field_validator("content_focus")
    @classmethod
    def normalize_content_focus(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            clean_item = item.strip()
            if not clean_item:
                continue
            if len(clean_item) > 100:
                raise ValueError("Content focus entries cannot exceed 100 characters")
            key = clean_item.casefold()
            if key not in seen:
                seen.add(key)
                normalized.append(clean_item)
        return normalized

    @model_validator(mode="after")
    def require_supplied_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one profile field is required")
        return self


class UserProfilePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    bio: str | None
    timezone: str | None
    preferred_language: str | None
    creator_identity: str | None
    content_focus: list[str]
    collaboration_preferences: str | None
    created_at: datetime
    updated_at: datetime
