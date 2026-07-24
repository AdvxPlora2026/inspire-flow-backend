from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
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


class BrandOrganization(Base):
    __tablename__ = "brand_organizations"
    __table_args__ = (Index("ix_brand_organizations_updated_at", "updated_at"),)

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(String(2048))
    logo_url: Mapped[str | None] = mapped_column(String(2048))
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class BrandMembership(Base):
    __tablename__ = "brand_memberships"
    __table_args__ = (
        UniqueConstraint(
            "brand_id",
            "user_id",
            name="uq_brand_memberships_brand_id_user_id",
        ),
        CheckConstraint("role IN ('owner', 'member')", name="role_valid"),
        Index("ix_brand_memberships_user_id_brand_id", "user_id", "brand_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    brand_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("brand_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="member", server_default=text("'member'")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class BrandInvitation(Base):
    __tablename__ = "brand_invitations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'revoked')",
            name="status_valid",
        ),
        Index(
            "ix_brand_invitations_invited_user_id_status",
            "invited_user_id",
            "status",
        ),
        Index(
            "uq_brand_invitations_pending",
            "brand_id",
            "invited_user_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
        ),
        Index("ix_brand_invitations_brand_id_status", "brand_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    brand_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("brand_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    invited_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    invited_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default=text("'pending'")
    )
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class BrandFollow(Base):
    __tablename__ = "brand_follows"
    __table_args__ = (
        UniqueConstraint(
            "brand_id",
            "creator_user_id",
            name="uq_brand_follows_brand_id_creator_user_id",
        ),
        CheckConstraint("status IN ('active', 'inactive')", name="status_valid"),
        Index("ix_brand_follows_creator_user_id_updated_at", "creator_user_id", "updated_at"),
        Index("ix_brand_follows_brand_id_status", "brand_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    brand_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("brand_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    creator_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default=text("'active'")
    )
    followed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    unfollowed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class BrandInterest(Base):
    __tablename__ = "brand_interests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'withdrawn')",
            name="status_valid",
        ),
        Index("ix_brand_interests_creator_user_id_updated_at", "creator_user_id", "updated_at"),
        Index("ix_brand_interests_brand_id_status", "brand_id", "status"),
        Index(
            "uq_brand_interests_pending",
            "brand_id",
            "creator_user_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    brand_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("brand_organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    creator_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default=text("'pending'")
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class CreatorInboxItem(Base):
    __tablename__ = "creator_inbox_items"
    __table_args__ = (
        UniqueConstraint(
            "kind",
            "reference_id",
            name="uq_creator_inbox_items_kind_reference_id",
        ),
        CheckConstraint("kind IN ('follow', 'interest')", name="kind_valid"),
        Index(
            "ix_creator_inbox_items_creator_user_id_event_at",
            "creator_user_id",
            "event_at",
        ),
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
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), nullable=False
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    event_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
