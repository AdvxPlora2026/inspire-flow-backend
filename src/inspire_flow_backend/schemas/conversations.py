from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from inspire_flow_backend.schemas.memories import UserMemoryPublic


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)
    archived: bool | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def validate_supplied_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one conversation field is required")
        if "archived" in self.model_fields_set and self.archived is None:
            raise ValueError("archived cannot be null")
        return self


class ConversationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime


class ConversationPage(BaseModel):
    items: list[ConversationPublic]
    total: int
    limit: int
    offset: int


class ConversationMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message content cannot be blank")
        return normalized


class ConversationMessagePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    turn_id: UUID
    sequence: int
    role: str
    content: str
    created_at: datetime


class ConversationMessagePage(BaseModel):
    items: list[ConversationMessagePublic]
    next_cursor: int | None
    limit: int


class AgentTurnPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    turn_id: UUID
    user_message: ConversationMessagePublic
    assistant_message: ConversationMessagePublic
    memory_updates: tuple[UserMemoryPublic, ...]
    memory_extraction_status: str
