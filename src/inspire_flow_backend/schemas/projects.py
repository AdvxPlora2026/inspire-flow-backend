from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

ProjectIconUrl = Annotated[HttpUrl, Field(max_length=2048)]


def _normalize_required(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        raise ValueError("Project field cannot be blank")
    return normalized


class ProjectFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    type: str = Field(min_length=1, max_length=50)
    audience: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=2_000)
    icon_url: ProjectIconUrl | None = None

    @field_validator("title", "type", "audience", "summary", mode="before")
    @classmethod
    def normalize_fields(cls, value: object) -> object:
        return _normalize_required(value)


class ProjectDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=4_000)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        return _normalize_required(value)


class ProjectDraft(ProjectFields):
    pass


class ProjectCreate(ProjectFields):
    pass


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    type: str | None = Field(default=None, min_length=1, max_length=50)
    audience: str | None = Field(default=None, min_length=1, max_length=500)
    summary: str | None = Field(default=None, min_length=1, max_length=2_000)
    icon_url: ProjectIconUrl | None = None

    @field_validator("title", "type", "audience", "summary", mode="before")
    @classmethod
    def normalize_fields(cls, value: object) -> object:
        if value is None:
            return None
        return _normalize_required(value)

    @model_validator(mode="after")
    def validate_supplied_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one project field is required")
        if any(
            field_name != "icon_url" and getattr(self, field_name) is None
            for field_name in self.model_fields_set
        ):
            raise ValueError("Project fields cannot be null")
        return self


class ProjectPublic(ProjectFields):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime


class ProjectPage(BaseModel):
    items: list[ProjectPublic]
    total: int
    limit: int
    offset: int
