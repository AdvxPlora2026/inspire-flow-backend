from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MemoryCategory(StrEnum):
    creative_focus = "creative_focus"
    creative_preference = "creative_preference"
    workflow_preference = "workflow_preference"
    collaboration_preference = "collaboration_preference"
    project_context = "project_context"
    personal_detail = "personal_detail"
    other = "other"


class MemoryStatus(StrEnum):
    active = "active"
    inactive = "inactive"


class MemoryOrigin(StrEnum):
    automatic = "automatic"
    explicit = "explicit"
    manual = "manual"


class UserMemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: MemoryCategory
    content: str = Field(min_length=1, max_length=2000)
    status: MemoryStatus = MemoryStatus.active
    is_sensitive: bool = False
    is_pinned: bool = False

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Memory content cannot be blank")
        return normalized


class UserMemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: MemoryCategory | None = None
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    status: MemoryStatus | None = None
    is_sensitive: bool | None = None
    is_pinned: bool | None = None

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Memory content cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_supplied_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one memory field is required")
        for field_name in self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class UserMemoryPublic(BaseModel):
    id: UUID
    user_id: UUID
    category: MemoryCategory
    content: str
    status: MemoryStatus
    origin: MemoryOrigin
    is_sensitive: bool
    is_pinned: bool
    user_edited: bool
    source_conversation_id: UUID | None
    source_deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserMemoryPage(BaseModel):
    items: list[UserMemoryPublic]
    total: int
    limit: int
    offset: int
