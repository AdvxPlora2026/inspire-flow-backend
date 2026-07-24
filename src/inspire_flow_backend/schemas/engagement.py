from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from inspire_flow_backend.schemas.workshops import WorkshopPublic


class FollowStatus(StrEnum):
    active = "active"
    inactive = "inactive"


class BrandFollowPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    brand_id: UUID
    creator_id: UUID
    status: FollowStatus
    followed_at: datetime
    unfollowed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BrandFollowPage(BaseModel):
    items: list[BrandFollowPublic]
    total: int
    limit: int
    offset: int


class InterestStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"
    withdrawn = "withdrawn"


class BrandInterestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_id: UUID
    message: str | None = Field(default=None, max_length=2000)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class BrandInterestPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    brand_id: UUID
    brand_name: str
    creator_id: UUID
    message: str | None
    status: InterestStatus
    created_by_user_id: UUID
    responded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BrandInterestPage(BaseModel):
    items: list[BrandInterestPublic]
    total: int
    limit: int
    offset: int


class BrandInterestUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: InterestStatus

    @model_validator(mode="after")
    def require_withdrawn(self) -> Self:
        if self.status != InterestStatus.withdrawn:
            raise ValueError("Brands can only withdraw pending interests")
        return self


class CreatorInterestUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: InterestStatus

    @model_validator(mode="after")
    def require_creator_transition(self) -> Self:
        if self.status not in {InterestStatus.accepted, InterestStatus.declined}:
            raise ValueError("Creators can only accept or decline pending interests")
        return self


class CreatorInboxItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_read: bool


class CreatorInboxMarkRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_ids: list[UUID] | None = Field(default=None, max_length=100)


class CreatorInboxItemPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: str
    brand_id: UUID
    brand_name: str
    reference_id: UUID
    status: str
    message: str | None
    is_read: bool
    read_at: datetime | None
    event_at: datetime
    created_at: datetime
    updated_at: datetime


class CreatorInboxPage(BaseModel):
    items: list[CreatorInboxItemPublic]
    total: int
    limit: int
    offset: int


class CreatorDiscoveryPage(BaseModel):
    items: list[WorkshopPublic]
    total: int
    limit: int
    offset: int


class DiscoverySortBy(StrEnum):
    published_at = "published_at"
    updated_at = "updated_at"


class DiscoverySortOrder(StrEnum):
    asc = "asc"
    desc = "desc"
