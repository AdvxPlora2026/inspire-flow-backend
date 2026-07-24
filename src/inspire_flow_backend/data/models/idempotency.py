from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
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


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "brand_id",
            "method",
            "route_template",
            "key_digest",
            name="uq_idempotency_records_scope_key",
        ),
        CheckConstraint("status IN ('processing', 'completed', 'failed')", name="status_valid"),
        Index(
            "uq_idempotency_records_user_scope_key",
            "user_id",
            "method",
            "route_template",
            "key_digest",
            unique=True,
            sqlite_where=text("brand_id IS NULL"),
        ),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("brand_organizations.id", ondelete="CASCADE"),
    )
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    route_template: Mapped[str] = mapped_column(String(255), nullable=False)
    key_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_headers: Mapped[str | None] = mapped_column(Text)
    response_ciphertext: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class AgentTurnRun(Base):
    __tablename__ = "agent_turn_runs"
    __table_args__ = (
        CheckConstraint("status IN ('processing', 'completed', 'failed')", name="status_valid"),
        Index("ix_agent_turn_runs_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid4
    )
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_record_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("idempotency_records.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    turn_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result_ciphertext: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
