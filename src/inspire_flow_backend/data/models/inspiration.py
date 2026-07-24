from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from inspire_flow_backend.core.time import utc_now
from inspire_flow_backend.data.base import Base
from inspire_flow_backend.data.types import UTCDateTime

if TYPE_CHECKING:
    from inspire_flow_backend.data.models.agent_conversation import AgentConversation
    from inspire_flow_backend.data.models.agent_message import AgentMessage
    from inspire_flow_backend.data.models.project import Project
    from inspire_flow_backend.data.models.user import User


inspiration_projects = Table(
    "inspiration_projects",
    Base.metadata,
    Column(
        "inspiration_id",
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("inspirations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "project_id",
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Index(
        "ix_inspiration_projects_project_id_inspiration_id",
        "project_id",
        "inspiration_id",
    ),
)


class Inspiration(Base):
    __tablename__ = "inspirations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('inbox', 'developing', 'converted', 'archived')",
            name="status_valid",
        ),
        CheckConstraint(
            "source_type IN ('manual', 'agent', 'voice')",
            name="source_type_valid",
        ),
        Index(
            "ix_inspirations_user_id_updated_at",
            "user_id",
            "updated_at",
        ),
        Index(
            "ix_inspirations_user_id_status_updated_at",
            "user_id",
            "status",
            "updated_at",
        ),
        Index(
            "ix_inspirations_source_conversation_id",
            "source_conversation_id",
        ),
        Index(
            "ix_inspirations_source_message_id",
            "source_message_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="inbox",
        server_default=text("'inbox'"),
    )
    source_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="manual",
        server_default=text("'manual'"),
    )
    source_conversation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("agent_conversations.id", ondelete="SET NULL"),
    )
    source_message_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("agent_messages.id", ondelete="SET NULL"),
    )
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
    user: Mapped["User"] = relationship(back_populates="inspirations")
    source_conversation: Mapped["AgentConversation | None"] = relationship()
    source_message: Mapped["AgentMessage | None"] = relationship()
    projects: Mapped[list["Project"]] = relationship(
        secondary=inspiration_projects,
        back_populates="inspirations",
        passive_deletes=True,
    )
