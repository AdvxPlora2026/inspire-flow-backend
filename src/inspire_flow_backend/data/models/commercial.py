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

TASK_STATUS_CHECK = (
    "('created', 'escrow_funded', 'submission_recorded', "
    "'authorization_activated', 'settlement_released')"
)
CHAIN_TX_STATUS_CHECK = "('prepared', 'broadcast', 'confirmed', 'failed')"
CHAIN_TX_ACTION_CHECK = (
    "('escrow_funded', 'submission_recorded', 'authorization_activated', 'settlement_released')"
)


class CommercialTask(Base):
    __tablename__ = "commercial_tasks"
    __table_args__ = (
        CheckConstraint(f"status IN {TASK_STATUS_CHECK}", name="status_valid"),
        Index("ix_commercial_tasks_user_id_updated_at", "user_id", "updated_at"),
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
    project_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    budget_amount: Mapped[str] = mapped_column(String(40), nullable=False)
    budget_denom: Mapped[str] = mapped_column(String(16), nullable=False)
    deadline: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="created",
        server_default=text("'created'"),
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class CommercialTaskSplit(Base):
    __tablename__ = "commercial_task_splits"
    __table_args__ = (
        CheckConstraint("bps >= 1 AND bps <= 10000", name="bps_valid"),
        UniqueConstraint("task_id", "party_id", name="uq_commercial_task_splits_task_party"),
        Index("ix_commercial_task_splits_task_id_sort_order", "task_id", "sort_order"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        primary_key=True,
        default=uuid4,
    )
    task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("commercial_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    party_id: Mapped[str] = mapped_column(String(100), nullable=False)
    bps: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CommercialTaskSubmission(Base):
    __tablename__ = "commercial_task_submissions"
    __table_args__ = (
        Index(
            "ix_commercial_task_submissions_task_id_created_at",
            "task_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        primary_key=True,
        default=uuid4,
    )
    task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("commercial_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        nullable=False,
    )
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class ChainTransaction(Base):
    __tablename__ = "chain_transactions"
    __table_args__ = (
        CheckConstraint(f"status IN {CHAIN_TX_STATUS_CHECK}", name="status_valid"),
        CheckConstraint(f"action IN {CHAIN_TX_ACTION_CHECK}", name="action_valid"),
        Index("ix_chain_transactions_task_id_created_at", "task_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        primary_key=True,
        default=uuid4,
    )
    task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("commercial_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="prepared",
        server_default=text("'prepared'"),
    )
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    chain_id: Mapped[str | None] = mapped_column(String(32))
    transaction_hash: Mapped[str | None] = mapped_column(String(128))
    nonce: Mapped[int | None] = mapped_column(Integer)
    explorer_url: Mapped[str | None] = mapped_column(String(2048))
    memo: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[str | None] = mapped_column(String(40))
    denom: Mapped[str | None] = mapped_column(String(16))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool | None] = mapped_column(Boolean)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
