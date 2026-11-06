"""Create orders and approvals tables

Revision ID: 0004_orders_approvals
Revises: 0003_carts_cart_items
Create Date: 2026-11-04 00:05:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0004_orders_approvals"
down_revision: Union[str, None] = "0003_carts_cart_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create orders table
    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("cart_id", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="pending_verification", nullable=False),
        sa.Column("intent_json", sa.JSON(), nullable=False),
        sa.Column("items_json", sa.JSON(), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("shipping", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("tax", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("checks_json", sa.JSON(), nullable=True),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("paypal_order_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_orders_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cart_id"], ["carts.id"], name="fk_orders_cart_id_carts", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_paypal_order_id", "orders", ["paypal_order_id"])

    # 2. Create approvals table
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("approved_version", sa.Integer(), nullable=False),
        sa.Column("approved_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="approved", nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_approvals_order_id_orders", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_approvals_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_approvals"),
    )
    op.create_index("ix_approvals_order_id", "approvals", ["order_id"])
    op.create_index("ix_approvals_user_id", "approvals", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_approvals_user_id", table_name="approvals")
    op.drop_index("ix_approvals_order_id", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index("ix_orders_paypal_order_id", table_name="orders")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_user_id", table_name="orders")
    op.drop_table("orders")
