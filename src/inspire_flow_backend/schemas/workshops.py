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

WorkshopUrl = Annotated[HttpUrl, Field(max_length=2048)]


class WorkshopVisibility(StrEnum):
    private = "private"
    workshop_public = "workshop_public"
    brands_only = "brands_only"
    authorized_brands = "authorized_brands"


class WorkshopStatus(StrEnum):
    draft = "draft"
    published = "published"
    withdrawn = "withdrawn"


class WorkshopPreviewAudience(StrEnum):
    owner = "owner"
    public = "public"
    brand = "brand"
    authorized_brand = "authorized_brand"


class SocialPlatform(StrEnum):
    bilibili = "bilibili"
    douyin = "douyin"
    xiaohongshu = "xiaohongshu"
    weibo = "weibo"
    zhihu = "zhihu"
    youtube = "youtube"
    other = "other"


class ContactType(StrEnum):
    email = "email"
    phone = "phone"
    wechat = "wechat"
    qq = "qq"
    telegram = "telegram"
    other = "other"


class ContactVisibility(StrEnum):
    private = "private"
    authorized_brands = "authorized_brands"


class WorkshopUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: str | None = Field(default=None, min_length=1, max_length=50)
    avatar_url: WorkshopUrl | None = None
    title: str | None = Field(default=None, max_length=120)
    bio: str | None = Field(default=None, max_length=4000)
    creator_identity: str | None = Field(default=None, max_length=100)
    content_focus: list[str] | None = Field(default=None, max_length=20)
    collaboration_preferences: str | None = Field(default=None, max_length=4000)
    nickname_visibility: WorkshopVisibility | None = None
    avatar_visibility: WorkshopVisibility | None = None
    title_visibility: WorkshopVisibility | None = None
    bio_visibility: WorkshopVisibility | None = None
    creator_identity_visibility: WorkshopVisibility | None = None
    content_focus_visibility: WorkshopVisibility | None = None
    collaboration_preferences_visibility: WorkshopVisibility | None = None

    @field_validator(
        "nickname",
        "title",
        "bio",
        "creator_identity",
        "collaboration_preferences",
    )
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("content_focus")
    @classmethod
    def normalize_content_focus(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if any(len(item) > 100 for item in normalized):
            raise ValueError("Content focus items cannot exceed 100 characters")
        return normalized

    @model_validator(mode="after")
    def require_supplied_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one workshop field is required")
        if "nickname" in self.model_fields_set and self.nickname is None:
            raise ValueError("Nickname cannot be null or blank")
        return self


class WorkshopSocialAccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: SocialPlatform
    handle: str | None = Field(default=None, max_length=120)
    profile_url: WorkshopUrl
    visibility: WorkshopVisibility = WorkshopVisibility.workshop_public
    sort_order: int = Field(default=0, ge=0, le=10_000)


class WorkshopSocialAccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: SocialPlatform | None = None
    handle: str | None = Field(default=None, max_length=120)
    profile_url: WorkshopUrl | None = None
    visibility: WorkshopVisibility | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)

    @model_validator(mode="after")
    def require_supplied_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one social account field is required")
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in ("platform", "profile_url", "visibility", "sort_order")
        ):
            raise ValueError("Required social account fields cannot be null")
        return self


class WorkshopSocialAccountPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    platform: SocialPlatform
    handle: str | None
    profile_url: str
    visibility: WorkshopVisibility | None = None
    sort_order: int


class WorkshopContactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ContactType
    label: str | None = Field(default=None, max_length=100)
    value: str = Field(min_length=1, max_length=500)
    visibility: ContactVisibility = ContactVisibility.private
    sort_order: int = Field(default=0, ge=0, le=10_000)


class WorkshopContactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ContactType | None = None
    label: str | None = Field(default=None, max_length=100)
    value: str | None = Field(default=None, min_length=1, max_length=500)
    visibility: ContactVisibility | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)

    @model_validator(mode="after")
    def require_supplied_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one contact field is required")
        if any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in ("type", "value", "visibility", "sort_order")
        ):
            raise ValueError("Required contact fields cannot be null")
        return self


class WorkshopContactPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    type: ContactType
    label: str | None
    value: str
    action_uri: str | None
    visibility: ContactVisibility | None = None
    sort_order: int


class WorkshopProjectSelectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: WorkshopVisibility = WorkshopVisibility.workshop_public
    sort_order: int = Field(default=0, ge=0, le=10_000)


class WorkshopProjectCardPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID | None
    title: str
    type: str
    audience: str
    summary: str
    icon_url: str | None
    visibility: WorkshopVisibility | None = None
    sort_order: int


class WorkshopDraftPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    status: WorkshopStatus
    nickname: str
    avatar_url: str | None
    title: str | None
    bio: str | None
    creator_identity: str | None
    content_focus: list[str]
    collaboration_preferences: str | None
    nickname_visibility: WorkshopVisibility
    avatar_visibility: WorkshopVisibility
    title_visibility: WorkshopVisibility
    bio_visibility: WorkshopVisibility
    creator_identity_visibility: WorkshopVisibility
    content_focus_visibility: WorkshopVisibility
    collaboration_preferences_visibility: WorkshopVisibility
    social_accounts: list[WorkshopSocialAccountPublic]
    contacts: list[WorkshopContactPublic]
    projects: list[WorkshopProjectCardPublic]
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkshopPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_id: UUID
    nickname: str | None
    avatar_url: str | None
    title: str | None
    bio: str | None
    creator_identity: str | None
    content_focus: list[str] | None
    collaboration_preferences: str | None
    social_accounts: list[WorkshopSocialAccountPublic]
    contacts: list[WorkshopContactPublic]
    projects: list[WorkshopProjectCardPublic]
    published_at: datetime | None


class WorkshopBrandAuthorizationPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_id: UUID
    brand_name: str
    active: bool
    granted_at: datetime
    revoked_at: datetime | None
