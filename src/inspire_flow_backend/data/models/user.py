from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.types import UTCDateTime

if TYPE_CHECKING:
    from inspire_flow_backend.data.models.agent_conversation import AgentConversation
    from inspire_flow_backend.data.models.auth_session import AuthSession
    from inspire_flow_backend.data.models.transcription_job import TranscriptionJob
    from inspire_flow_backend.data.models.user_memory import UserMemory
    from inspire_flow_backend.data.models.user_profile import UserProfile


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        primary_key=True,
        default=uuid4,
    )
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    nickname_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    profile: Mapped["UserProfile"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    conversations: Mapped[list["AgentConversation"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    memories: Mapped[list["UserMemory"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    transcription_jobs: Mapped[list["TranscriptionJob"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
