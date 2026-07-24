from datetime import datetime
from enum import StrEnum
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

BrandUrl = Annotated[HttpUrl, Field(max_length=2048)]


def _normalize_non_blank(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        raise ValueError("Field cannot be blank")
    return normalized


class BrandRole(StrEnum):
    owner = "owner"
    member = "member"


class BrandCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    website_url: BrandUrl | None = None
    logo_url: BrandUrl | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return _normalize_non_blank(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class BrandUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    website_url: BrandUrl | None = None
    logo_url: BrandUrl | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if value is None:
            return None
        return _normalize_non_blank(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def require_supplied_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one brand field is required")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Brand name cannot be null")
        return self


class BrandPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str | None
    website_url: str | None
    logo_url: str | None
    my_role: BrandRole
    created_at: datetime
    updated_at: datetime


class BrandPage(BaseModel):
    items: list[BrandPublic]
    total: int
    limit: int
    offset: int


class BrandInvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str = Field(min_length=2, max_length=50)

    @field_validator("nickname", mode="before")
    @classmethod
    def normalize_nickname(cls, value: object) -> object:
        return _normalize_non_blank(value)


class BrandInvitationPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    brand_id: UUID
    brand_name: str
    invited_user_id: UUID
    invited_by_user_id: UUID
    status: str
    responded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BrandMembershipPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    nickname: str
    role: BrandRole
    created_at: datetime


class BrandMemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: BrandRole
