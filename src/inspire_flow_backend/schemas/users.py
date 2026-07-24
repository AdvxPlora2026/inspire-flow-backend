from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)

from inspire_flow_backend.core.identity import clean_nickname

AvatarUrl = Annotated[HttpUrl, Field(max_length=2048)]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str
    password: SecretStr = Field(min_length=15, max_length=128)
    avatar_url: AvatarUrl | None = None

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value: str) -> str:
        return clean_nickname(value)


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str | None = None
    avatar_url: AvatarUrl | None = None

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_nickname(value)

    @model_validator(mode="after")
    def validate_supplied_fields(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one profile field is required")
        if "nickname" in self.model_fields_set and self.nickname is None:
            raise ValueError("Nickname cannot be null")
        return self


class UserProfileTextUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_text: str | None = Field(default=None, max_length=8000)

    @field_validator("profile_text")
    @classmethod
    def normalize_profile_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def require_supplied_field(self) -> Self:
        if "profile_text" not in self.model_fields_set:
            raise ValueError("Profile text field is required")
        return self


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nickname: str
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime
