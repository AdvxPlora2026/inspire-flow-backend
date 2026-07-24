from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.types import UTCDateTime

VISIBILITY_CHECK = "('private', 'workshop_public', 'brands_only', 'authorized_brands')"


class CreatorWorkshop(Base):
    __tablename__ = "creator_workshops"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published', 'withdrawn')", name="status_valid"),
        *(
            CheckConstraint(f"{field} IN {VISIBILITY_CHECK}", name=f"{field}_valid")
            for field in (
                "nickname_visibility",
                "avatar_visibility",
                "title_visibility",
                "bio_visibility",
                "creator_identity_visibility",
                "content_focus_visibility",
                "collaboration_preferences_visibility",
            )
        ),
        Index("ix_creator_workshops_status_updated_at", "status", "updated_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default=text("'draft'")
    )
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    title: Mapped[str | None] = mapped_column(String(120))
    bio: Mapped[str | None] = mapped_column(Text)
    creator_identity: Mapped[str | None] = mapped_column(String(100))
    content_focus: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default=text("'[]'")
    )
    collaboration_preferences: Mapped[str | None] = mapped_column(Text)
    nickname_visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="workshop_public"
    )
    avatar_visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="workshop_public"
    )
    title_visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="workshop_public"
    )
    bio_visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="workshop_public"
    )
    creator_identity_visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="workshop_public"
    )
    content_focus_visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="workshop_public"
    )
    collaboration_preferences_visibility: Mapped[str] = mapped_column(
        String(32), nullable=False, default="brands_only"
    )
    published_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False)
    )
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class WorkshopSocialAccount(Base):
    __tablename__ = "workshop_social_accounts"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('bilibili','douyin','xiaohongshu','weibo','zhihu','youtube','other')",
            name="platform_valid",
        ),
        CheckConstraint(f"visibility IN {VISIBILITY_CHECK}", name="visibility_valid"),
        Index(
            "ix_workshop_social_accounts_workshop_user_id_sort_order",
            "workshop_user_id",
            "sort_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    workshop_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("creator_workshops.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(120))
    profile_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class WorkshopContact(Base):
    __tablename__ = "workshop_contacts"
    __table_args__ = (
        CheckConstraint(
            "type IN ('email','phone','wechat','qq','telegram','other')",
            name="type_valid",
        ),
        CheckConstraint(
            "visibility IN ('private','authorized_brands')",
            name="visibility_valid",
        ),
        Index("ix_workshop_contacts_workshop_user_id_sort_order", "workshop_user_id", "sort_order"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    workshop_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("creator_workshops.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    label: Mapped[str | None] = mapped_column(String(100))
    value_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class WorkshopProjectSelection(Base):
    __tablename__ = "workshop_project_selections"
    __table_args__ = (
        UniqueConstraint(
            "workshop_user_id",
            "project_id",
            name="uq_workshop_project_selections_workshop_user_id_project_id",
        ),
        CheckConstraint(f"visibility IN {VISIBILITY_CHECK}", name="visibility_valid"),
        Index(
            "ix_workshop_project_selections_workshop_user_id_sort_order",
            "workshop_user_id",
            "sort_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    workshop_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("creator_workshops.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class WorkshopPublication(Base):
    __tablename__ = "workshop_publications"
    __table_args__ = (
        UniqueConstraint(
            "workshop_user_id",
            "version",
            name="uq_workshop_publications_workshop_user_id_version",
        ),
        Index(
            "ix_workshop_publications_workshop_user_id_published_at",
            "workshop_user_id",
            "published_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    workshop_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("creator_workshops.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class WorkshopPublicationSocialAccount(Base):
    __tablename__ = "workshop_publication_social_accounts"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    publication_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("workshop_publications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(120))
    profile_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class WorkshopPublicationContact(Base):
    __tablename__ = "workshop_publication_contacts"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    publication_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("workshop_publications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    label: Mapped[str | None] = mapped_column(String(100))
    value_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class WorkshopPublicationProjectCard(Base):
    __tablename__ = "workshop_publication_project_cards"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    publication_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("workshop_publications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_project_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("projects.id", ondelete="SET NULL"),
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    audience: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    icon_url: Mapped[str | None] = mapped_column(String(2048))
    visibility: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class WorkshopBrandAuthorization(Base):
    __tablename__ = "workshop_brand_authorizations"
    __table_args__ = (
        UniqueConstraint(
            "creator_user_id",
            "brand_id",
            name="uq_workshop_brand_authorizations_creator_user_id_brand_id",
        ),
        Index("ix_workshop_brand_authorizations_brand_id_active", "brand_id", "active"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    creator_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    brand_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("brand_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
