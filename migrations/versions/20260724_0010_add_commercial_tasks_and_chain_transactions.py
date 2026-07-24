"""add commercial tasks and chain transactions

Revision ID: 20260724_0010
Revises: 20260724_0009
Create Date: 2026-07-24 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import inspire_flow_backend.data.types

revision: str = "20260724_0010"
down_revision: str | Sequence[str] | None = "20260724_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_STATUS_VALUES = (
    "('created', 'escrow_funded', 'submission_recorded', "
    "'authorization_activated', 'settlement_released')"
)
CHAIN_TX_STATUS_VALUES = "('prepared', 'broadcast', 'confirmed', 'failed')"
CHAIN_TX_ACTION_VALUES = (
    "('escrow_funded', 'submission_recorded', 'authorization_activated', 'settlement_released')"
)


def upgrade() -> None:
    op.create_table(
        "commercial_tasks",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("user_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("project_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("budget_amount", sa.String(length=40), nullable=False),
        sa.Column("budget_denom", sa.String(length=16), nullable=False),
        sa.Column("deadline", inspire_flow_backend.data.types.UTCDateTime(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'created'"),
            nullable=False,
        ),
        sa.Column("created_at", inspire_flow_backend.data.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", inspire_flow_backend.data.types.UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            f"status IN {TASK_STATUS_VALUES}",
            name=op.f("ck_commercial_tasks_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_commercial_tasks_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_commercial_tasks_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commercial_tasks")),
    )
    with op.batch_alter_table("commercial_tasks", schema=None) as batch_op:
        batch_op.create_index(
            "ix_commercial_tasks_user_id_updated_at",
            ["user_id", "updated_at"],
            unique=False,
        )

    op.create_table(
        "commercial_task_splits",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("task_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("party_id", sa.String(length=100), nullable=False),
        sa.Column("bps", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "bps >= 1 AND bps <= 10000",
            name=op.f("ck_commercial_task_splits_bps_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["commercial_tasks.id"],
            name=op.f("fk_commercial_task_splits_task_id_commercial_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commercial_task_splits")),
        sa.UniqueConstraint(
            "task_id",
            "party_id",
            name="uq_commercial_task_splits_task_party",
        ),
    )
    with op.batch_alter_table("commercial_task_splits", schema=None) as batch_op:
        batch_op.create_index(
            "ix_commercial_task_splits_task_id_sort_order",
            ["task_id", "sort_order"],
            unique=False,
        )

    op.create_table(
        "commercial_task_submissions",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("task_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("artifact_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("delivery_url", sa.String(length=2048), nullable=False),
        sa.Column("created_at", inspire_flow_backend.data.types.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["commercial_tasks.id"],
            name=op.f("fk_commercial_task_submissions_task_id_commercial_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commercial_task_submissions")),
    )
    with op.batch_alter_table("commercial_task_submissions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_commercial_task_submissions_task_id_created_at",
            ["task_id", "created_at"],
            unique=False,
        )

    op.create_table(
        "chain_transactions",
        sa.Column("id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("task_id", sa.Uuid(native_uuid=False), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'prepared'"),
            nullable=False,
        ),
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.Column("chain_id", sa.String(length=32), nullable=True),
        sa.Column("transaction_hash", sa.String(length=128), nullable=True),
        sa.Column("explorer_url", sa.String(length=2048), nullable=True),
        sa.Column("memo", sa.Text(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.String(length=40), nullable=True),
        sa.Column("denom", sa.String(length=16), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("submitted_at", inspire_flow_backend.data.types.UTCDateTime(), nullable=True),
        sa.Column("confirmed_at", inspire_flow_backend.data.types.UTCDateTime(), nullable=True),
        sa.Column("created_at", inspire_flow_backend.data.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at", inspire_flow_backend.data.types.UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            f"status IN {CHAIN_TX_STATUS_VALUES}",
            name=op.f("ck_chain_transactions_status_valid"),
        ),
        sa.CheckConstraint(
            f"action IN {CHAIN_TX_ACTION_VALUES}",
            name=op.f("ck_chain_transactions_action_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["commercial_tasks.id"],
            name=op.f("fk_chain_transactions_task_id_commercial_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chain_transactions")),
    )
    with op.batch_alter_table("chain_transactions", schema=None) as batch_op:
        batch_op.create_index(
            "ix_chain_transactions_task_id_created_at",
            ["task_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("chain_transactions", schema=None) as batch_op:
        batch_op.drop_index("ix_chain_transactions_task_id_created_at")
    op.drop_table("chain_transactions")

    with op.batch_alter_table("commercial_task_submissions", schema=None) as batch_op:
        batch_op.drop_index("ix_commercial_task_submissions_task_id_created_at")
    op.drop_table("commercial_task_submissions")

    with op.batch_alter_table("commercial_task_splits", schema=None) as batch_op:
        batch_op.drop_index("ix_commercial_task_splits_task_id_sort_order")
    op.drop_table("commercial_task_splits")

    with op.batch_alter_table("commercial_tasks", schema=None) as batch_op:
        batch_op.drop_index("ix_commercial_tasks_user_id_updated_at")
    op.drop_table("commercial_tasks")
