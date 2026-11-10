"""Create transactions and audit_events tables

Revision ID: 0005_transactions_audit
Revises: 0004_orders_approvals
Create Date: 2026-11-04 00:20:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0005_transactions_audit"
down_revision: Union[str, None] = "0004_orders_approvals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create transactions table
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("product", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("method", sa.String(length=50), server_default="PayPal Sandbox", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="Completed", nullable=False),
        sa.Column("verification", sa.String(length=50), server_default="Backend verified", nullable=False),
        sa.Column("paypal_reference", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_transactions_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_transactions_order_id_orders", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_order_id", "transactions", ["order_id"])

    # 2. Create audit_events table
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("timestamp", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_audit_events_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_user_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_transactions_order_id", table_name="transactions")
    op.drop_index("ix_transactions_user_id", table_name="transactions")
    op.drop_table("transactions")
