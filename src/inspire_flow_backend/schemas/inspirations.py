from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from inspire_flow_backend.schemas.projects import ProjectIconUrl


class InspirationStatus(StrEnum):
    inbox = "inbox"
    developing = "developing"
    converted = "converted"
    archived = "archived"


class InspirationSourceType(StrEnum):
    manual = "manual"
    agent = "agent"
    voice = "voice"


class InspirationSortBy(StrEnum):
    created_at = "created_at"
    updated_at = "updated_at"


class SortOrder(StrEnum):
    asc = "asc"
    desc = "desc"


PublicSourceType = Literal["manual", "voice"]
ProjectIds = Annotated[list[UUID], Field(max_length=100)]


def _normalize_required(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        raise ValueError("Inspiration content cannot be blank")
    return normalized


def _normalize_optional_title(value: object) -> object:
    if value is None or not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        raise ValueError("Inspiration title cannot be blank")
    return normalized


def _unique_project_ids(value: list[UUID]) -> list[UUID]:
    if len(set(value)) != len(value):
        raise ValueError("Project IDs must be unique")
    return value


class InspirationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)
    content: str = Field(min_length=1, max_length=20_000)
    status: InspirationStatus = InspirationStatus.inbox
    source_type: PublicSourceType = "manual"
    project_ids: ProjectIds = Field(default_factory=list)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return _normalize_optional_title(value)

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, value: object) -> object:
        return _normalize_required(value)

    @field_validator("project_ids")
    @classmethod
    def validate_project_ids(cls, value: list[UUID]) -> list[UUID]:
        return _unique_project_ids(value)


class InspirationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)
    content: str | None = Field(default=None, min_length=1, max_length=20_000)
    status: InspirationStatus | None = None
    project_ids: ProjectIds | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        return _normalize_optional_title(value)

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, value: object) -> object:
        if value is None:
            return None
        return _normalize_required(value)

    @field_validator("project_ids")
    @classmethod
    def validate_project_ids(
        cls,
        value: list[UUID] | None,
    ) -> list[UUID] | None:
        if value is None:
            return None
        return _unique_project_ids(value)

    @model_validator(mode="after")
    def validate_supplied_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one inspiration field is required")
        if "content" in self.model_fields_set and self.content is None:
            raise ValueError("Inspiration content cannot be null")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("Inspiration status cannot be null")
        if "project_ids" in self.model_fields_set and self.project_ids is None:
            raise ValueError("Project IDs cannot be null")
        return self


class InspirationProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    title: str
    icon_url: ProjectIconUrl | None


class InspirationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    user_id: UUID
    title: str | None
    content: str
    status: InspirationStatus
    source_type: InspirationSourceType
    source_conversation_id: UUID | None
    source_message_id: UUID | None
    projects: list[InspirationProjectSummary]
    created_at: datetime
    updated_at: datetime


class InspirationPage(BaseModel):
    items: list[InspirationPublic]
    total: int
    limit: int
    offset: int
